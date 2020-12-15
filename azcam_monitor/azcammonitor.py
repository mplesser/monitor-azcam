# AzCam Monitor class

import configparser
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time

import psutil
from azcam_monitor.webserver.web_server import WebServer

import azcam


class DataItem(object):
    def __init__(self):
        self.number = 0
        self.type = 0
        self.pid = 0
        self.name = ""
        self.cmd_port = 0
        self.host = ""
        self.path = ""
        self.flags = 0
        self.watchdog = 0
        self.count = 0


class AzCamMonitor(socketserver.ThreadingTCPServer, socketserver.ThreadingUDPServer):
    def __init__(self):

        self.debug = 1

        # UDP port used for receiving register_process requests
        self.port_reg = 2400
        self.port_udp = 2400
        self.port_data = 2401
        self.remote_ip = 0

        self.UDPServer = 0
        self.UDPServer_running = 0

        self.timer_server = 0
        self.timer_server_running = 0

        self.RegServer = 0
        self.RegServer_running = 0

        self.cmd_host = socket.gethostbyname(socket.gethostname())
        self.cmd_port = 0

        self.udp_socket = 0

        self.IDs = []
        self.Resp = []

        # Registered processes - use Lock() to access current data
        self.MonitorData = []

        self.MonitorDataSemafor = threading.Lock()

        self.process_number = 0

        # Create first entry in the MonitorData list
        self.NewDataItem = DataItem()
        self.NewDataItem.type = 1
        self.NewDataItem.pid = os.getpid()
        self.NewDataItem.name = "azcam-monitor"
        self.NewDataItem.cmd_port = self.port_reg
        # For monitor use IP address instead of the path
        self.NewDataItem.path = self.cmd_host
        self.NewDataItem.flags = 0
        self.MonitorData.append(self.NewDataItem)

        # command line args
        try:
            i = sys.argv.index("-configfile")
            self.config_file = sys.argv[i + 1]
        except ValueError:
            self.config_file = None

    def start_server(self):
        """
        Starts UDP server in a separate thread.
        """

        print(f"Starting server - listening on port {self.port_udp}/udp")
        regthread = threading.Thread(target=self.init_server)
        regthread.start()

        return

    def stop_server(self):
        """
        Stops UDP server running in separate thread.
        """

        self.UDPServer.shutdown()
        self.UDPServer_running = 0

        return

    def init_server(self, port=-1):
        """
        Start UDP (ID and Register) process server.
        Last change: 06Mar2019 Zareba
        """
        if port == -1:
            port = self.port_udp
        else:
            self.port_udp = port

        server_address = ("", port)  # '' better than localhost when no network
        self.saddr = server_address
        self.UDPServer = ThreadedUDPServer(server_address, GetUDPRequestHandler)
        self.UDPServer.MonData = self.MonitorData
        self.UDPServer.MonDataSemafor = self.MonitorDataSemafor
        self.UDPServer.CallParser = self.command_parser
        self.UDPServer.port_data = self.port_data
        self.UDPServer.Debug = self.debug
        # self.RegServer.PtrIDs = self.MonitorID

        try:
            self.UDPServer_running = 1
            self.UDPServer.serve_forever()  # blocking loop
        except Exception as message:
            self.UDPServer_running = 0
            print("ERROR init_server: %s Is it already running? Exiting..." % repr(message))

        # Exits here when server is aborted

        return

    def start_watchdog(self):
        """
        Starts watchdog server in a separate thread.
        """
        watchdogthread = threading.Thread(target=self.init_watchdog)
        watchdogthread.start()

        return

    def stop_watchdog(self):
        """
        Stops watchdog loop running in separate thread.
        """

        # self.timer_server.shutdown()
        self.timer_server_running = 0

        return

    def init_watchdog(self):
        """
        Start Timer/watchdog server.
        """

        self.timer_server = self.watchdog_loop()
        self.timer_server.MonData = self.MonitorData
        self.timer_server.MonDataSemafor = self.MonitorDataSemafor

        try:
            self.timer_server_running = 1
            self.timer_server.serve_forever()  # blocking loop
        except Exception as message:
            self.timer_server_running = 0
            print("ERROR init_watchdog: %s Is it already running? Exiting..." % repr(message))
        return

    def watchdog_loop(self):
        """
        watchdog main loop.
        """

        while True:
            # Check the counter regularly
            time.sleep(0.5)

            self.MonitorDataSemafor.acquire()

            # Get the total count of MonitorData items
            cnt = len(self.MonitorData)

            # Check if all active processes are running
            for indx in range(1, cnt):
                # Check the watchdog value
                watchdog = int(self.MonitorData[indx].watchdog)
                if watchdog > 0:
                    # Check if the process is running
                    self.MonitorData[indx].count = int(self.MonitorData[indx].count) + 1

                    if int(self.MonitorData[indx].count) > watchdog * 2:
                        self.MonitorData[indx].count = 0

                        pid = self.MonitorData[indx].pid
                        running = 0
                        for procItem in psutil.process_iter():
                            # Check if process with current ID is running
                            if procItem.pid == pid:
                                running = 1

                        if running == 0:
                            # Process is not running -> restart the process
                            path = self.MonitorData[indx].path
                            print(
                                "Process "
                                + self.MonitorData[indx].name
                                + " on port "
                                + self.MonitorData[indx].cmd_port
                                + " is not responding. Restarting process..."
                            )
                            subprocess.Popen(path, creationflags=subprocess.CREATE_NEW_CONSOLE)

                        else:
                            # Check if the process is responding (use TCP connection)
                            cmd_port = self.MonitorData[indx].cmd_port
                            try:
                                testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                testSocket.settimeout(1)
                                testSocket.connect((self.cmd_host, cmd_port))

                                echo = "echo\r\n"

                                testSocket.send(str.encode(echo))
                                testSocket.recv(1024)
                                testSocket.close()
                                # Process is responding -> do nothing
                            except Exception:
                                # Keep the path to the process
                                path = self.MonitorData[indx].path

                                print(
                                    "Process "
                                    + self.MonitorData[indx].name
                                    + " on port "
                                    + self.MonitorData[indx].cmd_port
                                    + " is not responding. Terminating process..."
                                )
                                # Process is not responding -> stop it and start again
                                subprocess.Popen(
                                    "taskkill /F /T /pid " + str(self.MonitorData[indx].pid)
                                )
                                time.sleep(0.1)

                                # Start the process. Process should register itself and it will keep the same spot in the MonitorData struct.
                                subprocess.Popen(path, creationflags=subprocess.CREATE_NEW_CONSOLE)

            self.MonitorDataSemafor.release()

        return

    def load_configfile(self, config_file=None):
        """
        Load configuration file with list of processes that should be automatically started.
        """

        if config_file is None:
            config_file = self.config_file
        else:
            self.config_file = config_file

        if self.config_file is None:
            return

        update = "update\r\n"

        print("Loading monitor config file: " + config_file)

        self.MonitorConfig = configparser.ConfigParser()

        self.MonitorConfig.read(config_file)

        # Load all processes
        # This happens only when the AzCam Monitor starts -> there are no processes already registered
        for process_section in self.MonitorConfig.sections():
            cmd_port = int(self.MonitorConfig.get(process_section, "cmd_port"))

            try:

                testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testSocket.settimeout(1)
                testSocket.connect((self.cmd_host, cmd_port))

                testSocket.send(str.encode(update))
                testSocket.recv(1024)
                testSocket.close()
            except Exception:
                start = int(self.MonitorConfig.get(process_section, "start"))
                if start == 1:
                    # Start the process -> the process will register itself
                    if self.debug:
                        print(
                            "Process "
                            + self.MonitorConfig.get(process_section, "name")
                            + " is not running"
                        )

                    path = self.MonitorConfig.get(process_section, "path")
                    if self.debug:
                        print("Starting a new process " + path)
                    print(
                        "Starting "
                        + self.MonitorConfig.get(process_section, "name")
                        + " on port "
                        + str(cmd_port)
                    )
                    subprocess.Popen(path, creationflags=subprocess.CREATE_NEW_CONSOLE)
                    time.sleep(0.2)

                else:
                    # Make new entry in the DataItem list -> the process is not started yet
                    if self.debug:
                        print(
                            "Process "
                            + self.MonitorConfig.get(process_section, "name")
                            + " is not running"
                        )

                    # Create nee Data Item
                    self.NewDataItem = DataItem()

                    # Set process number - unique
                    self.NewDataItem.number = self.process_number + 1
                    self.process_number += 1

                    self.NewDataItem.pid = 0
                    self.NewDataItem.name = self.MonitorConfig.get(process_section, "name")
                    self.NewDataItem.cmd_port = int(
                        self.MonitorConfig.get(process_section, "cmd_port")
                    )
                    self.NewDataItem.host = self.cmd_host
                    self.NewDataItem.path = self.MonitorConfig.get(process_section, "path")
                    self.NewDataItem.flags = self.MonitorConfig.get(process_section, "flags")

                    # Append new DataItem
                    self.MonitorData.append(self.NewDataItem)

        return

    def command_parser(self, RegData):
        """
        Called when a request is received.
        """

        # Command codes:
        # 0 - send IDs
        # 1 - register process - add process to the MonitorData struct
        # 2 - add process - add a process to the MonitorData struct and start it (process will register itself)
        # 3 - remove process - remove process with given command port number
        # 4 - start process - start process with given command port number
        # 5 - stop process - stop process with given command port number
        # 6 - restart process - restart process with given command port number
        # 7 - stop all processes - stop all currently running processes
        # 8 - start all processes - start all processes with start flag set to 1
        # 9 - refresh all processes - check which processes are running (try to connect to all processes listed in the MonitorData struct)
        # 10 - start a process based on name not command port

        retVal = "OK"

        # Get the command code
        self.Recv = RegData.split(" ")
        cmd = int(self.Recv[0])

        if cmd == 0:
            # Send back IDs of all running processes
            retVal = self.get_ids()

        elif cmd == 1:
            # Register process
            retVal = self.register_process()

        elif cmd == 2:
            # Add process to the MonitorData struct
            retVal = self.add_process(self.Recv)

        elif cmd == 3:
            # Remove process
            if len(self.Recv) == 2:
                if int(self.Recv[1]) > 0:
                    self.remove_process(int(self.Recv[1]))
                else:
                    retVal = "ERROR: Can't remove AzCam Monitor process (s)"
            else:
                retVal = "ERROR: Wrong parameter(s)"

        elif cmd == 4:
            # Start process
            retVal = self.start_process(int(self.Recv[1]))

        elif cmd == 5:
            # Stop process
            retVal = self.stop_process(int(self.Recv[1]))

        elif cmd == 6:
            # Restart process
            retVal = self.restart_process(int(self.Recv[1]))

        elif cmd == 7:
            # Stop all processes
            retVal = self.stop_all_processes()

        elif cmd == 8:
            # Start all processes
            retVal = self.start_all_processes()

        elif cmd == 9:
            # Refresh processes
            retVal = self.refresh_processes()

        else:
            retVal = "ERROR: Unsupported command"

        return retVal

    def get_ids(self):
        """
        Return IDs of all processes.
        """

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)

        msg = ""
        self.process_list = []
        data_list = []
        for indx in range(cnt):
            data_list = [
                str(self.MonitorData[indx].number),
                str(self.MonitorData[indx].pid),
                self.MonitorData[indx].name,
                str(self.MonitorData[indx].cmd_port),
                self.MonitorData[indx].host,
                self.MonitorData[indx].path,
                str(self.MonitorData[indx].flags),
                str(self.MonitorData[indx].watchdog),
            ]
            msg = " ".join(data_list)
            self.process_list.append(data_list)

        self.MonitorDataSemafor.release()

        return msg

    def register_process(self):
        """
        Register process.
        """

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        found = 0
        cmd_port = int(self.Recv[3])
        procPos = 0
        retVal = "OK"

        # Check if the process is already registerd and running in the MonitorData list
        for indx in range(cnt):
            if self.MonitorData[indx].cmd_port == cmd_port:
                if self.MonitorData[indx].pid > 0:
                    # Entry the MonitorData list found and process is probably running
                    found = 1
                    procPos = indx
                else:
                    # Entry the MonitorData list found and process is probably not running
                    found = 2
                    procPos = indx

        if found == 1:
            # Entry the MonitorData list found and process is probably running
            running = 0
            for procItem in psutil.process_iter():
                # Check if process with current ID is running
                if procItem.pid == self.MonitorData[procPos].pid:
                    running = 1

            if running:
                # Process is already running -> terminate the process which sent register command
                retVal = (
                    "Attempt to register process "
                    + self.MonitorData[indx].name
                    + " on port "
                    + str(cmd_port)
                    + " has failed. Process already running."
                )
                # subprocess.Popen("taskkill /F /T /pid " + self.Recv[1])
            else:
                # Data entry in the MonitorData struct should be updated
                self.MonitorData[procPos].pid = int(self.Recv[1])
                self.MonitorData[procPos].name = self.Recv[2]
                self.MonitorData[procPos].cmd_port = int(self.Recv[3])
                self.MonitorData[procPos].host = self.Recv[4]
                self.MonitorData[procPos].path = self.Recv[5]
                self.MonitorData[procPos].flags = self.Recv[6]
                self.MonitorData[procPos].watchdog = self.Recv[7]

                retVal = (
                    "Process "
                    + self.MonitorData[procPos].name
                    + " was running on port "
                    + str(self.MonitorData[procPos].cmd_port)
                )

        elif found == 2:
            # Re-register process (process was previously registered then stopped)
            retVal = (
                "Process "
                + self.MonitorData[procPos].name
                + " is running on port "
                + str(self.NewDataItem.cmd_port)
            )
            # Update pid and watchdog time
            self.MonitorData[procPos].pid = int(self.Recv[1])
            self.MonitorData[procPos].watchdog = self.Recv[7]

        elif found == 0:
            # Register new process

            self.NewDataItem = DataItem()
            recvCnt = len(self.Recv)
            try:
                if recvCnt == 8:
                    self.NewDataItem.number = self.process_number + 1
                    self.process_number += 1

                    self.NewDataItem.type = 0
                    self.NewDataItem.pid = int(self.Recv[1])
                    self.NewDataItem.name = self.Recv[2]
                    self.NewDataItem.cmd_port = int(self.Recv[3])
                    self.NewDataItem.host = self.Recv[4]
                    self.NewDataItem.path = self.Recv[5]
                    self.NewDataItem.flags = self.Recv[6]
                    self.NewDataItem.watchdog = self.Recv[7]

                    # Append new DataItem
                    self.MonitorData.append(self.NewDataItem)

                    retVal = (
                        "Process "
                        + self.NewDataItem.name
                        + " is running on port "
                        + str(self.NewDataItem.cmd_port)
                    )
                else:
                    # ERROR - registration string
                    retVal = "ERROR: Process Registration string error"

            except Exception as message:
                retVal = "ERROR: Register Process " % repr(message)

        self.MonitorDataSemafor.release()

        print(retVal)

        return retVal

    def add_process(self, addStr):
        """
        Add new process to the MonitorData struct.
        """

        self.MonitorDataSemafor.acquire()

        recvCnt = len(addStr)

        try:
            if recvCnt == 6:

                self.NewDataItem = DataItem()
                self.NewDataItem.number = self.process_number + 1
                self.process_number += 1

                self.NewDataItem.type = 0
                self.NewDataItem.pid = 0
                self.NewDataItem.name = addStr[1]
                self.NewDataItem.cmd_port = int(addStr[2])
                self.NewDataItem.host = addStr[3]
                self.NewDataItem.path = addStr[4]
                self.NewDataItem.flags = addStr[5]
                self.NewDataItem.watchdog = addStr[6]
                self.NewDataItem.count = 0

                # Append new DataItem
                self.MonitorData.append(self.NewDataItem)

                # Start the process -> the process will register itself

                path = self.NewDataItem.path

                subprocess.Popen(path, creationflags=subprocess.CREATE_NEW_CONSOLE)
                time.sleep(0.2)
                print("Process: " + self.NewDataItem.name + " is added/registered")

                retVal = "Process: " + self.NewDataItem.name + " is added/registered\r\n"
        except Exception as message:
            retVal = "ERROR Add/Register..." % repr(message)

        self.MonitorDataSemafor.release()

        return retVal

    def remove_process(self, Proccmd_port):
        """
        Remove process. Stop the process if running then remove.
        """
        cmd_port = int(Proccmd_port)

        # Check if the process is running
        print("Removing process on cmd_port " + str(cmd_port))

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        sleepT = 0

        pos = 0
        for indx in range(cnt):
            if self.MonitorData[indx].cmd_port == cmd_port:
                pos = indx
                procName = self.MonitorData[indx].name
                pID = self.MonitorData[indx].pid
                if pID == 0:
                    # Set sleep time in case the process is running but not updated in the DataItem list
                    sleepT = 1.0

        if pos > 0:
            update = "update\r\n"
            # Process entry found -> check if process is running
            try:
                testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                testSocket.settimeout(1)

                testSocket.connect((self.cmd_host, self.MonitorData[pos].cmd_port))

                retVal = testSocket.send(str.encode(update))
                testSocket.recv(1024)
                testSocket.close()

                # Wait for the process to send update to the monitor (if the process is running)
                time.sleep(sleepT)
                # Close the process
                subprocess.Popen("taskkill /F /T /pid " + str(pID))
                time.sleep(0.1)
                self.MonitorData[pos].pid = 0
                retVal = "Process: " + procName + " has been removed"
            except Exception:
                # Time out -> process not running
                retVal = "Process: " + procName + " is not responding"

        else:
            retVal = "Process: " + procName + " not found"

        # Remove the process from the DataItem list
        del self.MonitorData[pos]

        self.MonitorDataSemafor.release()

        return retVal

    def start_process(self, name=None, cmd_port=None):
        """
        Start process. Do nothing if process is running.
        """

        if cmd_port is not None:
            cmd_port = int(cmd_port)

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        found = 0

        # Find the process in the MonitorData struct
        for indx in range(cnt):

            if (name is None and self.MonitorData[indx].cmd_port == cmd_port) or (
                cmd_port is None and self.MonitorData[indx].name == name
            ):
                found = 1
                if self.MonitorData[indx].pid == 0:
                    p = subprocess.Popen(
                        self.MonitorData[indx].path,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                    time.sleep(0.1)
                    self.MonitorData[indx].pid = int(p.pid)
                    retVal = "Process: " + self.MonitorData[indx].name + " has been started"
                else:
                    # Check if process is running
                    try:
                        testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        testSocket.settimeout(1)
                        testSocket.connect((self.cmd_host, self.MonitorData[indx].cmd_port))
                        testSocket.close()
                        retVal = "Process: " + self.MonitorData[indx].name + " is already running"
                    except Exception:
                        # Process is not running
                        p = subprocess.Popen(
                            self.MonitorData[indx].path,
                            creationflags=subprocess.CREATE_NEW_CONSOLE,
                        )
                        self.MonitorData[indx].pid = int(p.pid)
                        time.sleep(0.1)
                        retVal = "Process: " + self.MonitorData[indx].name + " has been started"

        if found == 0:
            retVal = "Process: " + str(cmd_port) + " not found"

        self.MonitorDataSemafor.release()

        return retVal

    def stop_process(self, name=None, cmd_port=None):
        """
        Stop running process.
        """

        if cmd_port is not None:
            cmd_port = int(cmd_port)

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        found = 0

        for indx in range(cnt):
            if (name is None and self.MonitorData[indx].cmd_port == cmd_port) or (
                cmd_port is None and self.MonitorData[indx].name == name
            ):
                found = 1
                if self.MonitorData[indx].pid == 0:
                    # Process ID = 0 -> process not running
                    retVal = "Process: " + self.MonitorData[indx].name + " is not running"
                else:
                    # Process ID != 0 -> process is running
                    self.MonitorData[indx].watchdog = 0
                    subprocess.Popen("taskkill /F /T /pid " + str(self.MonitorData[indx].pid))
                    time.sleep(0.1)
                    self.MonitorData[indx].pid = 0
                    retVal = "Process: " + self.MonitorData[indx].name + " has been stopped"

        if found == 0:
            retVal = "Process: " + self.MonitorData[indx].name + " not found"
            if self.debug:
                print(retVal)

        self.MonitorDataSemafor.release()

        return retVal

    def stop_all_processes(self):
        """
        Stop all running processes.
        """

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        stopCnt = 0

        for indx in range(1, cnt):
            # Check if the process is running
            if self.MonitorData[indx].pid != 0:
                # Stop the watchdog so the process will not be restarted
                self.MonitorData[indx].watchdog = 0
                self.MonitorData[indx].count = 0
                # Stop the process
                subprocess.Popen("taskkill /F /T /pid " + str(self.MonitorData[indx].pid))
                self.MonitorData[indx].pid = 0
                stopCnt += 1

        retVal = "Stopped: " + str(stopCnt) + " processes"
        if self.debug:
            print(retVal)

        self.MonitorDataSemafor.release()

        return retVal

    def start_all_processes(self):
        """
        Start all processes previously registerd.
        """

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        startCnt = 0

        for indx in range(1, cnt):
            if self.MonitorData[indx].pid == 0:
                subprocess.Popen(
                    self.MonitorData[indx].path,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                time.sleep(0.1)
                startCnt += 1
                # The process will register itself
                if self.debug:
                    print("Starting : " + str(self.MonitorData[indx].name) + " process")

        self.MonitorDataSemafor.release()

        retVal = "Started: " + str(startCnt) + " processes"

        return retVal

    def restart_process(self, procNum):
        """
        Restart process. Stop it and then start.
        Use process number as the reference.
        """

        self.MonitorDataSemafor.acquire()

        cnt = len(self.MonitorData)
        procPos = 0

        for indx in range(1, cnt):
            if int(self.MonitorData[indx].number) == procNum:
                procPos = indx

        if procPos > 0:
            # Check if the process is running
            cmd_port = self.MonitorData[procPos].cmd_port
            echo = "echo\r\n"
            try:
                testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testSocket.settimeout(1)
                testSocket.connect((self.cmd_host, cmd_port))

                retVal = testSocket.send(str.encode(echo))
                testSocket.recv(1024)
                testSocket.close()

                # Process is running -> close it

                subprocess.Popen("taskkill /F /T /pid " + str(self.MonitorData[procPos].pid))
                time.sleep(0.1)
                self.MonitorData[procPos].pid = 0
            except Exception:
                if self.MonitorData[procPos].pid > 0:
                    self.MonitorData[procPos].pid = 0

            # Here process should be closed -> start it
            path = self.MonitorData[procPos].path
            subprocess.Popen(path, creationflags=subprocess.CREATE_NEW_CONSOLE)
            # Give the process some time to register itself
            time.sleep(0.3)

            retVal = "OK"
        else:
            retVal = "ERROR Process not found"

        self.MonitorDataSemafor.release()

        return retVal

    def refresh_processes(self):
        """
        Refresh process. Each process from the DataItem list is checked and the DataItem list is updated.
        """

        cnt = len(self.MonitorData)

        update = "echo test\r\n"
        for indx in range(1, cnt):

            # Check if the process is running
            cmd_port = self.MonitorData[indx].cmd_port

            try:
                testSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                testSocket.settimeout(1)
                testSocket.connect((self.cmd_host, cmd_port))

                retVal = testSocket.send(str.encode(update))
                testSocket.recv(1024)
                testSocket.close()

                # Process is running -> it should update its entry in the DataItem list
                time.sleep(0.2)
            except Exception:
                # Time out -> process is not running
                if self.MonitorData[indx].pid > 0:
                    self.MonitorData[indx].pid = 0

        retVal = "OK"

        return retVal

    def get_status(self):
        """
        Return process status.
        """

        response = {}

        cnt = len(self.MonitorData)
        for indx in range(cnt):

            rsp = {}
            rsp["procnum"] = str(self.MonitorData[indx].number)
            rsp["pid"] = str(self.MonitorData[indx].pid)
            rsp["name"] = self.MonitorData[indx].name
            rsp["cmd_port"] = str(self.MonitorData[indx].cmd_port)
            rsp["host"] = self.MonitorData[indx].host
            rsp["path"] = self.MonitorData[indx].path
            rsp["flags"] = str(self.MonitorData[indx].flags)
            rsp["watchdog"] = str(self.MonitorData[indx].watchdog)

            response[f"process{indx}"] = rsp

        return response

    def print_monitor_data(self):
        """
        Prints all MonitorData items.
        """

        cnt = len(self.MonitorData)
        for indx in range(cnt):
            msg = "PNum: " + str(self.MonitorData[indx].number)
            print(msg)
            msg = "pid: " + str(self.MonitorData[indx].pid)
            print(msg)
            msg = "name: " + self.MonitorData[indx].name
            print(msg)
            msg = "CommandPort: " + str(self.MonitorData[indx].cmd_port)
            print(msg)
            msg = "host: " + self.MonitorData[indx].host
            print(msg)
            msg = "path: " + self.MonitorData[indx].path
            print(msg)
            msg = "flags: " + str(self.MonitorData[indx].flags)
            print(msg)
            msg = "watchdog: " + str(self.MonitorData[indx].watchdog)
            print(msg)
            msg = "watchdog counter: " + str(self.MonitorData[indx].count)
            print(msg)

        return

    #   ***********************************************************************
    #   webserver
    #   ***********************************************************************
    def start_webserver(self):
        self.webserver = WebServer()
        self.webserver.azcammonitor = self
        self.webserver.start()


class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    allow_reuse_address = True


class GetUDPRequestHandler(socketserver.BaseRequestHandler):
    def __init__(self, request, client_address, server):

        self.cmdVal = 0
        self.Resp = ""
        socketserver.BaseRequestHandler.__init__(self, request, client_address, server)

    def setup(self):
        return socketserver.BaseRequestHandler.setup(self)

    def handle(self):
        """
        Responses to the UDP reqests.
        """

        # Get remote IP address
        remote_ip = self.client_address[0]
        self.server.remote_ip = remote_ip

        try:
            # The UDP packet is already received -> get the first token (message-command)

            cmd = self.request[0].decode("utf-8")
            # First character is the command code. For now '0' - ID request, '1' - Register request
            self.cmdVal = cmd[0]

            # Call command parser
            self.Resp = self.server.CallParser(cmd)

        except Exception as message:
            print(message)

        return

    def finish(self):
        """
        Send response to the UDP request.
        """

        # Wait [100 + random] ms delay before sending response
        tm = str(time.time()).split(".")[1][0:3]
        tm = (int(tm) / 2 + 100) / 1000
        time.sleep(tm)

        # Create socket and send back ID strings
        udp_socketData = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socketData.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        udp_socketData.sendto(
            bytes(self.Resp, "utf-8"), (self.client_address[0], self.server.port_data)
        )
        udp_socketData.close()

        return socketserver.BaseRequestHandler.finish(self)


# start process
monitor = AzCamMonitor()
# monitor.load_configfile("/data/code/azcam-vatt/bin/parameters_vatt_monitor.ini")
monitor.load_configfile()
monitor.start_server()
monitor.start_watchdog()
monitor.print_monitor_data()
monitor.start_webserver()
