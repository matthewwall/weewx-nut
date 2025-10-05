# installer for the weewx-nut driver
# Copyright 2025 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

from weecfg.extension import ExtensionInstaller

def loader():
    return NUTInstaller()

class NUTInstaller(ExtensionInstaller):
    def __init__(self):
        super(NUTInstaller, self).__init__(
            version="0.1",
            name='nut',
            description='Capture data from UPS/PDU using NUT',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            files=[('bin/user', ['bin/user/nut.py'])]
            )
