#!/usr/bin/env python
# Copyright 2025 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)
"""
Collect data from UPS/PDU using NUT.
"""

from __future__ import with_statement
import os
import subprocess
import time

import weewx.drivers
import weewx.units

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
        syslog.syslog(level, 'nut: %s: %s' %
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

class NUTConfigurationEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[NUT]
    # The driver to use
    driver = user.nut
    # The name of the device, defined in the NUT configuration ups.conf
    device = REPLACE_ME
"""

class NUTDriver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        path = stn_dict.get('path', None)
        ld_library_path = stn_dict.get('ld_library_path', None)
        self._device = stn_dict.get('device', 'ups')
        loginf('device=%s' % self._device)
        self._poll_interval = stn_dict.get('poll_interval', 30)
        loginf('poll_interval=%s' % self._poll_interval)
        self._cmd = ['upsc', self._device]
        loginf("cmd='%s'" % ' '.join(self._cmd))
        pairs = run_cmd(self._cmd)
        self._model = pairs.get('device.model', 'NUT')
        loginf('model=%s' % self._model)

    def closePort(self):
        pass

    @property
    def hardware_name(self):
        return self._model

    def genLoopPackets(self):
        cmd = ['upsc', self._device])
        while True:
            pairs = run_cmd(cmd)
            time.sleep(self._poll_interval)

def run_cmd(cmd, path=None, ld_library_path=None):
    loginf("run command '%s'" % ' '.join(cmd))
    env = os.environ.copy()
    if path:
        env['PATH'] = path + ':' + env['PATH']
    if ld_library_path:
        env['LD_LIBRARY_PATH'] = ld_library_path
    pairs = dict()
    try:
        p = subprocess.Popen(cmd,
                             env=env,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        o = p.communicate()[0]
        for line in o.split('\n'):
            parts = line.split(':')
            if len(parts) == 2:
                name = strip(parts[0])
                value = strip(parts[1])
                pairs[name] = value
    except (OSError, ValueError) as e:
        raise weewx.WeeWxIOError("failed process '%s': %s" %
                                 (' '.join(cmd), e))
    return pairs


def main():
    import optparse

    usage = """%prog [--debug] [--help] [--version]
        [--path=PATH] [--ld_library_path=LD_LIBRARY_PATH]
    """

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', dest='version', action='store_true',
                      help='display driver version')
    parser.add_option('--debug', dest='debug', action='store_true',
                      help='display diagnostic information while running')
    parser.add_option('--path', dest='path',
                      help='value for PATH')
    parser.add_option('--ld_library_path', dest='ld_library_path',
                      help='value for LD_LIBRARY_PATH')

    (options, args) = parser.parse_args()

    if options.version:
        print("nut driver version %s" % DRIVER_VERSION)
        exit(1)

    if options.debug:
        pass # FIXME


if __name__ == '__main__':
    main()
