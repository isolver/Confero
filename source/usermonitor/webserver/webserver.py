# -*- coding: utf-8 -*-
from __future__ import division
"""
Created on Mon Feb 17 17:51:58 2014

@author: Sol
"""

import tornado
from tornado import websocket
from tornado.web import RequestHandler
import tornado.ioloop
from tornado.ioloop import IOLoop

from proc_util import startSubProcess,startNodeWebStreamer,quiteSubprocs

import timeit,time
IOLoop.time=timeit.default_timer

from webbrowser import open_new_tab
import string,  Queue
import random
import os
import ujson

def keyChainValue(cdict, *key_path):
    result = cdict.get(key_path[0])
    key_path = list(key_path[1:])
    for key in key_path:
        if not hasattr(result, 'get'):
            return result
        result = result.get(key)
    return result

#### Restful Handlers
class RestAppHandler(tornado.web.RequestHandler):
    server_app=None

class RestAppRpcHandler(RestAppHandler):
    def get(self,slug):
        path_tokens=slug.split('/')
        calls={}
        skipped=[]
        for pt in path_tokens:
            if pt and hasattr(self.server_app,pt):
                if pt.lower().endswith('quit') or pt.lower().endswith('quit/'):
                    print("Calling quit()")
                    self.server_app.quit()
                    return
                r = getattr(self.server_app, pt)()
                if r:
                    self.redirect(r)
                    return
                else:
                    calls.append(pt)
            else:
                skipped.append(pt)

        response={"rpc_mapped":calls,'rpc_notfound':skipped}
        self.write(response)


# Standard App Handlers

class BaseHandler(tornado.web.RequestHandler):
    pass
#    def get_current_user(self):
#        return self.get_secure_cookie("user")
#
#    def get_user_locale(self):
#        if hasattr(self.current_user, 'prefs'):
#            return self.current_user.prefs.get('locale', None)
        
class MainHandler(BaseHandler):
    #@tornado.web.authenticated
    def get(self):
        #name = tornado.escape.xhtml_escape(self.current_user)
        #
        appconfig = ControlFeedbackServer.app_config
        vshost = keyChainValue(appconfig, 'screen_capture',
                               'http_stream',
                               'host')
        rport = keyChainValue(appconfig,
                              'screen_capture',
                              'http_stream',
                              'read_port')
        vstream_scale = keyChainValue(appconfig,
                                      'screen_capture',
                                      'http_stream',
                                      'ffmpeg_settings',
                                      'scale')
        screen_cap_width, screen_cap_height = keyChainValue(appconfig,
                                  'screen_capture',
                                  'screen_resolution')
        screen_cap_width = int(screen_cap_width*vstream_scale)
        screen_cap_height = int(screen_cap_height*vstream_scale)

        self.render("index.html", video_server_host=vshost,
                    video_server_port=rport,
                    video_canvas_width=screen_cap_width,
                    video_canvas_height=screen_cap_height)

class ShutdownHandler(BaseHandler):
    def get(self):
        self.render("shutdown.html")
#
## Websocket server for sending / receiving msg's from Experiment Feedback Monitor
#
class WebSocket(websocket.WebSocketHandler):
    server_app_websockets = None
    ws_key = None
    def open(self):
        self.set_nodelay(True)
        print "\n**{0} opened.\n".format(self.__class__.__name__)
        self.server_app_websockets[self.ws_key] = self

    def on_message(self, message):
        print("{0} TO HANDLE: ".format(self.__class__.__name__), ujson.loads(message))

    def on_pong(self, data):
        #Invoked when the response to a ping frame is received.
        try:
            websocket.WebSocketHandler.on_pong(self,data)
        except tornado.websocket.WebSocketClosedError, e:
            try:
                del self.server_app_websockets[self.ws_key]
            except:
                pass
            raise e

    def on_close(self):
        print "\n** {0} closed.\n".format(self.__class__.__name__)
        try:
            del self.server_app_websockets[self.ws_key]
        except:
            pass

class UIWebSocket(WebSocket):
    ws_key="WEB_UI"

    def on_message(self, message):
        msg_dict= ujson.loads(message)
        print("{0} TO HANDLE: ".format(self.__class__.__name__),msg_dict)
        dc_sw= self.server_app_websockets.get("DATA_COLLECTION")
        if dc_sw:
            dc_sw.write_message(message)
        else:
            print("")
            print("WARNING: Data Collection Web Socket is not Running. Msg not sent. Is the Data Collection application running?")
            print("")

class DataCollectionWebSocket(WebSocket):
    ws_key = "DATA_COLLECTION"

    def on_message(self, message):
        #print("DATA_COLLECTION WS SENDING TO UI_WS:",len(message))
        msg_list = ujson.loads(message)
        to_send=[]
        for m in msg_list:
            msg_type = m.get('msg_type', 'UNKNOWN')
            if msg_type is not 'UNKNOWN':
                to_send.append(m)
        if len(to_send)>0:
            ws_ui=self.server_app_websockets.get("WEB_UI")
            if ws_ui:
                #print ("SENDING TO UI:",to_send)
                ws_ui.write_message(ujson.dumps(to_send))
            else:
                print(">> Warning: Message was not sent to Feedback Web UI:",to_send)
###############################################################################

class ControlFeedbackServer(object):
    settings = {
        "static_path": os.path.join(os.path.dirname(__file__), "static"),
        #"cookie_secret": 'ICXQQRAC45OG',
        #"login_url": "/login",
        #"xsrf_cookies": True,
    }

    handlers=[
            (r"/", MainHandler),
            #(r"/login", LoginHandler),
            #(r"/login", LoginHandler),
            (r"/shutdown", ShutdownHandler),
            #(r"/sandbox/(.*)",SandboxHandler),
            (r"/ui_websocket",UIWebSocket),
            (r"/data_websocket",DataCollectionWebSocket),
            (r"/rest_app/rpc/(.*)",RestAppRpcHandler),
            (r"/(apple-touch-icon\.png)", tornado.web.StaticFileHandler,
             dict(path=settings['static_path'])),
            ]

    get_cmd_queue = Queue.Queue()
    get_event_queue = Queue.Queue()
    web_sockets = dict()
    app_config = None
    def __init__(self, app_config):
        self.webapp = tornado.web.Application(self.handlers, **self.settings)
        self.ssproxy = None
        ControlFeedbackServer.app_config = app_config
        UIWebSocket.server_app_websockets = self.web_sockets
        DataCollectionWebSocket.server_app_websockets = self.web_sockets
        RestAppRpcHandler.server_app = self

    def serveForever(self):
        try: 
            self.ssproxy=startNodeWebStreamer(self.app_config)
            time.sleep(.5)
    
            # Start webapp server
            self.webapp.listen(8888)
    
            IOLoop.instance().add_timeout(self.getServerTime()+0.5,
                                          self.openWebAppGUI)
    
            tornado.locale.load_translations(
                os.path.join(os.path.dirname(__file__), "translations"))
    
            IOLoop.instance().start()
        except Exception, e:
            print('WEBAPP_SERVER EXCETION:', e)
        else:
            print('WEBAPP_SERVER STOPPED OK')
            
            
    def quit(self):
        def _exit():
            print 'Quiting Tornado server.....'
            if self.ssproxy:
                quiteSubprocs([self.ssproxy,])
                self.ssproxy=None
            IOLoop.instance().stop()
            print 'Tornado server stopped OK.'
        IOLoop.instance().add_timeout(self.getServerTime()+2.0,_exit)

    #def _terminate(self):

    @staticmethod
    def getServerTime():
        return IOLoop.time()

    @staticmethod
    def openWebAppGUI():
        appconfig = ControlFeedbackServer.app_config
        server_ip = keyChainValue(appconfig,
                               'experimenter_server',
                               'address')
        server_port = keyChainValue(appconfig,
                               'experimenter_server',
                               'port')
        open_new_tab('http://%s:%d/'%(server_ip,server_port))

    @staticmethod
    def id_generator(size=12, chars=string.ascii_uppercase + string.digits):
        return ''.join(random.choice(chars) for x in range(size))

    def __del__(self):
        self.quit()

###############################################################################
            

# class SandboxHandler(BaseHandler):
#    # def get(self, uri):
#        # self.render(os.path.normcase("sandbox\\"+uri))
#class LoginHandler(BaseHandler):
#    def get(self):
#        self.render("login.html")
#
#    def post(self):
#        self.set_secure_cookie("user", self.get_argument("username"))
#        password=self.get_argument("password")
#        rememberme=False
#        try:
#            rememberme=self.get_argument("rememberme")
#        except:
#            pass
#        self.redirect("/")

#class LogoutHandler(BaseHandler):
#    def get(self):
#        #self.write("Goodbye, " + self.current_user)
#        self.clear_cookie("user")
#        self.render("logout.html")