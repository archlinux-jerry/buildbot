#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import logging
from utils import bash
from yaml import load, dump
from pathlib import Path

logger = logging.getLogger(__name__)

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

# include all autobuild.yaml files

REPO_NAME = Path('repo')
BUTOBUILD_FNAME = 'autobuild.yaml'
for mydir in REPO_NAME.iterdir():
    if mydir.is_dir() and (mydir / BUTOBUILD_FNAME).exists():
        # parsing yaml
        logger.info('Bulidbot: found %s in %s', BUTOBUILD_FNAME, mydir / BUTOBUILD_FNAME)

