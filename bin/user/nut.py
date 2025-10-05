#!/usr/bin/env python
# Copyright 2025 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)
"""
Collect data from UPS/PDU using NUT.
"""

from __future__ import with_statement
from calendar import timegm
import fnmatch
import os
import re
import subprocess
import threading
import time
import copy

try:
    # Python 3
    import queue
except ImportError:
    # Python 2:
    import Queue as queue

import weewx.drivers
import weewx.units
from weeutil.weeutil import tobool

try:
    # logging in weewx 4+
    import weeutil.logger
    import logging
    log = logging.getLogger(__name__)
    def logdbg(msg):
        log.debug(msg)
    def loginf(msg):
        log.info(msg)
    def logerr(msg):
        log.error(msg)
except ImportError:
    # logging in weewx 3
    import syslog
    def logmsg(level, msg):
        syslog.syslog(level, 'sdr: %s: %s' %
                      (threading.currentThread().getName(), msg))
    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)
    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)
    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)

DRIVER_NAME = 'NUT'
DRIVER_VERSION = '0.1'

def loader(config_dict, _):
    return NUTDriver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return NUTConfigurationEditor()

class AsyncReader(threading.Thread):

    def __init__(self, fd, queue, label):
        threading.Thread.__init__(self)
        self._fd = fd
        self._queue = queue
        self._running = False
        self.setDaemon(True)
        self.setName(label)

    def run(self):
        logdbg("start async reader for %s" % self.getName())
        self._running = True
        for line in iter(self._fd.readline, ''):
            if line:
                self._queue.put(line)
            if not self._running:
                break

    def stop_running(self):
        self._running = False


class ProcManager(object):
    TS = re.compile('^\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d[\s]+')

    def __init__(self):
        self._cmd = None
        self._process = None
        self.stdout_queue = queue.Queue()
        self.stdout_reader = None
        self.stderr_queue = queue.Queue()
        self.stderr_reader = None

    def startup(self, cmd, path=None, ld_library_path=None):
        self._cmd = cmd
        loginf("startup process '%s'" % self._cmd)
        env = os.environ.copy()
        if path:
            env['PATH'] = path + ':' + env['PATH']
        if ld_library_path:
            env['LD_LIBRARY_PATH'] = ld_library_path
        try:
            self._process = subprocess.Popen(cmd.split(' '),
                                             env=env,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE)
            self.stdout_reader = AsyncReader(
                self._process.stdout, self.stdout_queue, 'stdout-thread')
            self.stdout_reader.start()
            self.stderr_reader = AsyncReader(
                self._process.stderr, self.stderr_queue, 'stderr-thread')
            self.stderr_reader.start()
        except (OSError, ValueError) as e:
            raise weewx.WeeWxIOError("failed to start process '%s': %s" %
                                     (cmd, e))

    def shutdown(self):
        loginf('shutdown process %s' % self._cmd)
        self._process.kill()
        logdbg("close stdout")
        self._process.stdout.close()
        logdbg("close stderr")
        self._process.stderr.close()
        logdbg('shutdown %s' % self.stdout_reader.getName())
        self.stdout_reader.stop_running()
        self.stdout_reader.join(0.5)
        logdbg('shutdown %s' % self.stderr_reader.getName())
        self.stderr_reader.stop_running()
        self.stderr_reader.join(0.5)
        if self._process.poll() is None:
            logerr('process did not respond to kill, shutting down anyway')
        self._process = None
        if self.stdout_reader.is_alive():
            loginf('timed out waiting for %s' % self.stdout_reader.getName())
        self.stdout_reader = None
        if self.stderr_reader.is_alive():
            loginf('timed out waiting for %s' % self.stderr_reader.getName())
        self.stderr_reader = None
        loginf('shutdown complete')

    def running(self):
        return self._process.poll() is None

    def get_stderr(self):
        lines = []
        while not self.stderr_queue.empty():
            lines.append(self.stderr_queue.get().decode())
        return lines

    def get_stdout(self):
        lines = []
        while self.running():
            try:
                # Fetch the output line. For it to be searched, Python 3
                # requires that it be decoded to unicode. Decoding does no
                # harm under Python 2:
                line = self.stdout_queue.get(True, 3).decode()
                m = ProcManager.TS.search(line)
                if m and lines:
                    yield lines
                    lines = []
                lines.append(line)
            except queue.Empty:
                yield lines
                lines = []
        yield lines


class NUTConfigurationEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[NUT]
    # The driver to use
    driver = user.nut
"""


class NUTDriver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        self._model = stn_dict.get('model', 'NUT')
        loginf('model is %s' % self._model)
        self._device = stn_dict.get('device', 'ups')
        path = stn_dict.get('path', None)
        ld_library_path = stn_dict.get('ld_library_path', None)
        self._mgr = ProcManager()
        self._mgr.startup(device, path, ld_library_path)

    def closePort(self):
        self._mgr.shutdown()

    @property
    def hardware_name(self):
        return self._model

    def genLoopPackets(self):
        while self._mgr.running():
            for lines in self._mgr.get_stdout():
                if self._log_lines:
                    loginf("lines: %s" % lines)
                pkt = self._lines_to_packet(lines)
                yield pkt
            # report any errors
            for line in self._mgr.get_stderr():
                logerr(line)
        else:
            for line in self._mgr.get_stderr():
                logerr(line)
            raise weewx.WeeWxIOError("nut client not running")


def main():
    import optparse
    import syslog

    usage = """%prog [--debug] [--help] [--version]
        [--cmd=RTL_CMD] [--path=PATH] [--ld_library_path=LD_LIBRARY_PATH]

Actions:
  show-packets: display each packet (default)
  show-detected: display a running count of the number of each packet type
  list-supported: show a list of the supported packet types

Hide:
  This is a comma-separate list of the types of data that should not be
  displayed.  Default is to show everything."""

    syslog.openlog('sdr', syslog.LOG_PID | syslog.LOG_CONS)
    syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', dest='version', action='store_true',
                      help='display driver version')
    parser.add_option('--debug', dest='debug', action='store_true',
                      help='display diagnostic information while running')
    parser.add_option('--cmd', dest='cmd', default=DEFAULT_CMD,
                      help='rtl command with options')
    parser.add_option('--path', dest='path',
                      help='value for PATH')
    parser.add_option('--ld_library_path', dest='ld_library_path',
                      help='value for LD_LIBRARY_PATH')
    parser.add_option('--config',
                      help='configuration file with sensor map')

    (options, args) = parser.parse_args()

    if options.version:
        print("sdr driver version %s" % DRIVER_VERSION)
        exit(1)

    if options.debug:
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))

    sensor_map = dict()
    if options.config:
        import weecfg
        config_path, config_dict = weecfg.read_config(options.config)
        sensor_map = config_dict.get('SDR', {}).get('sensor_map', {})

    mgr = ProcManager()
    mgr.startup(options.cmd, path=options.path,
                ld_library_path=options.ld_library_path)
    for lines in mgr.get_stdout():
        print(lines)
        for line in mgr.get_stderr():
            line = line.rstrip()
            print("err: %s" % line)


if __name__ == '__main__':
    main()
