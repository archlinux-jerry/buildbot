#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
from utils import bash

logger = logging.getLogger(name='package')


# makepkg -o
# makepkg -e
# makepkg --nosign
# makepkg --packagelist
# gpg --default-key {GPG_KEY} --no-armor --pinentry-mode loopback --passphrase '' --detach-sign --yes -- aaa
