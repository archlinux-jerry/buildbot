#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
from pathlib import Path

from utils import print_exc_plus

logger = logging.getLogger(f'buildbot.{__name__}')

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)
