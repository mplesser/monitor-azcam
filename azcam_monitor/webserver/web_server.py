"""
Configure and start Flask web server application.
"""

import sys
import threading
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request

import azcam

"""
Pages:
http://locahost:2400/

API:
/api/start_process?name=vatt4k (vatt4k, vattspec, mont4k, 90prime, bcspec)

/api/start_process?cmd_port=2402
"""


class WebServer(object):
    """
    Monitor-azcam web server.
    """

    def __init__(self):

        # create flask app
        app = Flask(__name__, template_folder="")
        self.app = app

        self.logcommands = 1

        # define pages
        index_home = "index.html"

        #: port for webserver
        self.webport = 2400

        self.is_running = 0

        # ******************************************************************************
        # home pages
        # ******************************************************************************
        @app.route("/", methods=["GET"])
        @app.route("/index", methods=["GET"])
        def index():
            # get new list each time page is refreshed
            self.azcammonitor.refresh_processes()
            self.azcammonitor.get_ids()
            return render_template(index_home, process_list=self.azcammonitor.process_list)

        # ******************************************************************************
        # api commands
        # ******************************************************************************
        # @app.route("/api/<path:command>", methods=["GET"])
        @app.route("/api/<path:command>", methods=["GET"])
        def api(command):
            """
            Remote web commands such as: /exposure/reset
            """

            url = request.url
            if self.logcommands:
                print(url)
            reply = self.webapi(url)

            return self.make_response(command, reply)

    def webapi(self, url):
        """
        Parse a web URL and make call to proper object method, returning reply.
        """

        try:
            caller, kwargs = self.webparse(url)
            reply = self.webcall(caller, kwargs)
        except azcam.AzcamError as e:
            if e.error_code == 4:
                reply = "remote call not allowed"
        except Exception as e:
            print(repr(e))
            reply = "ERROR executing remote web command"

        return reply

    def webparse(self, url):
        """
        Parse URL.
        """

        s = urlparse(url)
        p = s.path[5:]  # remove /api/

        try:
            obj, method = p.split("/")
        except Exception as e:
            raise e("Invalid API command")

        args = s.query.split("&")

        if args == [""]:
            kwargs = None
        else:
            kwargs = {}
            for arg1 in args:
                arg, par = arg1.split("=")
                kwargs[arg] = par

        # security check
        if obj != "monitor":
            raise azcam.AzcamError(f"remote call not allowed: {obj}", 4)

        caller = getattr(azcam._monitor, method)

        return caller, kwargs

    def webcall(self, caller, kwargs):
        """
        Make api call from webapi result.
        """

        reply = caller() if kwargs is None else caller(**kwargs)

        return reply

    def make_response(self, command, reply):

        # generic response
        response = {
            "message": "Finished",
            "command": command,
            "data": reply,
        }

        response = jsonify(response)

        return response

    def stop(self):
        """
        Stops command server running in thread.
        """

        print("Stopping the webserver is not supported")

        return

    def start(self):
        """
        Start web server.
        """

        print(f"Starting webserver - listening on port {self.webport}/tcp")

        # turn off development server warning
        cli = sys.modules["flask.cli"]
        cli.show_server_banner = lambda *x: None

        if 1:
            import logging

            log1 = logging.getLogger("werkzeug")
            log1.setLevel(logging.ERROR)

        # 0 => threaded for command line use (when imported)
        if 0:
            self.app.jinja_env.auto_reload = True
            self.app.config["TEMPLATES_AUTO_RELOAD"] = True
            self.app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False
            self.app.run(debug=True, threaded=False, host="0.0.0.0", port=self.webport)
        else:
            self.app.jinja_env.auto_reload = True
            self.app.config["TEMPLATES_AUTO_RELOAD"] = True
            self.app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True
            self.webthread = threading.Thread(
                target=self.app.run,
                kwargs={"threaded": True, "host": "0.0.0.0", "port": self.webport},
            )
            self.webthread.daemon = True  # terminates wehn main process exits
            self.webthread.start()
            self.is_running = 1

        return
