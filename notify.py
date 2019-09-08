#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# notify.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

from utils import background
import subprocess

# wip
# does nothing
@background
def send(content):
    try:
        subprocess.run(['python', 'tgapi.py', str(content)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass
