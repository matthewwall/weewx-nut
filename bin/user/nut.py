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

# these are fields from NUT that we report during driver initialization
INFO_FIELDS = [
    'device.model',
    'device.serial',
    'device.type',
    'device.mfr',
    'driver.parameter.pollfreq',
    'driver.parameter.pollinterval',
    'driver.parameter.port',
    'driver.parameter.synchronous',
    'driver.parameter.vendorid',
    'driver.version',
    'driver.version.data',
    'battery.charge.low',
    'battery.charge.warning',
    'battery.runtime.low',
    'battery.type',
    'input.voltage.nominal',
    'ups.beeper.status',
    'ups.delay.shutddown',
    'ups.delay.start',
    'ups.vendorid',
    'ups.productid',
    'ups.realpower.nominal',
]

# these are fields that we report in each observation cycle.  the names that
# show up as observations are these fields with the period replaced by an
# underscore.  the underscore names are what we use as the database fields.
OBS_FIELDS = [
    'input.voltage',
    'output.voltage',
    'battery.charge',
    'battery.runtime',
    'battery.voltage',
    'ups.load',
]

schema = [('dateTime', 'INTEGER NOT NULL UNIQUE PRIMARY KEY'),
          ('usUnits', 'INTEGER NOT NULL'),
          ('interval', 'INTEGER NOT NULL'),
          ('input_voltage', 'REAL'), # volt
          ('output_voltage', 'REAL'), # volt
          ('battery_charge', 'REAL'), # percent
          ('battery_runtime', 'REAL'), # second
          ('battery_voltage', 'REAL'), # volt
          ('ups_load', 'REAL'), # percent
]

weewx.units.obs_group_dict['input_voltage'] = 'group_volt'
weewx.units.obs_group_dict['output_voltage'] = 'group_volt'
weewx.units.obs_group_dict['battery_charge'] = 'group_percent'
weewx.units.obs_group_dict['battery_runtime'] = 'group_elapsed'
weewx.units.obs_group_dict['battery_voltage'] = 'group_volt'
weewx.units.obs_group_dict['ups_load'] = 'group_percent'


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
    def prompt_for_settings(self):
        print("Specify the name of the device as it appears in ups.conf")
        device = self._prompt('device', 'ups')
        return {'device', device}

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
        for label in INFO_FIELDS:
            loginf('%s=%s' % (label, pairs.get(label)))

    def closePort(self):
        pass

    @property
    def hardware_name(self):
        return self._model

    def genLoopPackets(self):
        cmd = ['upsc', self._device]
        while True:
            packet = {
                'dateTime': int(time.time() + 0.5),
                'usUnits': weewx.US,
            }
            pairs = run_cmd(cmd)
            for field in OBS_FIELDS:
                if field in pairs:
                    name = field.replace('.', '_')
                    packet[name] = float(pairs[field])
            yield packet
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
                name = parts[0].strip()
                value = parts[1].strip()
                pairs[name] = value
    except (OSError, ValueError) as e:
        raise weewx.WeeWxIOError("failed process '%s': %s" %
                                 (' '.join(cmd), e))
    return pairs


def main():
    import optparse
    from weeutil.weeutil import to_sorted_string

    usage = """%prog [--debug] [--help] [--version]
        [--path=PATH] [--ld_library_path=LD_LIBRARY_PATH]
    """

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', action='store_true',
                      help='display driver version')
    parser.add_option('--debug', action='store_true',
                      help='display diagnostic information while running')
    parser.add_option('--path',
                      help='value for PATH')
    parser.add_option('--ld_library_path',
                      help='value for LD_LIBRARY_PATH')
    parser.add_option('--device', default='ups',
                      help='device name from ups.conf')
    parser.add_option('--poll-interval',
                      help='how often to poll the nut server')

    (options, args) = parser.parse_args()

    if options.version:
        print("nut driver version %s" % DRIVER_VERSION)
        exit(0)

    if options.debug:
        weewx.debug = 1

    config_dict = {
        'NUT': {
            'device': options.device,
        }
    }
    if options.path:
        config_dict['NUT']['path'] = options.path
    if options.ld_library_path:
        config_dict['NUT']['ld_library_path'] = options.ld_library_path
    if options.poll_interval:
        config_dict['NUT']['poll_interval'] = int(options.poll_interval)

    driver = loader(config_dict, None)

    for pkt in driver.genLoopPackets():
        print(to_sorted_string(pkt))


if __name__ == '__main__':
    main()
