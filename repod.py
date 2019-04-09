#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repod.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Listener
from time import time, sleep
from pathlib import Path
from subprocess import CalledProcessError
import os

from config import REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD, REPO_PUSH_BANDWIDTH, \
                   GPG_VERIFY_CMD




from repo import _clean_archive as clean, \
                 _regenerate as regenerate, \
                 _remove as remove, \
                 _update as update

from utils import bash, configure_logger, print_exc_plus

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

logger = logging.getLogger('buildbot')
configure_logger(logger, logfile='repod.log', rotate_size=1024*1024*10)

class pushFm:
    def __init__(self):
        self.fname = None
        self.size = None
        self.start_time = None
        self.end_time = None
    def start(self, fname, size):
        '''
            size is in MB
            returns -1 when busy
        '''
        if self.is_busy():
            return -1
        self.fname = fname
        self.start_time = time()
        self.size = size
        if size <= 7.5:
            timeout = 120
            self.end_time = self.start_time + 120
        else:
            timeout = size / (REPO_PUSH_BANDWIDTH / 8) * 2
        self.end_time = self.start_time + timeout
        return timeout
    def tick(self):
        '''
            return None means success
            else returns an error string
        '''
        if self.is_busy():
            if time() > self.end_time:
                ret = f'file {self.fname} is supposed to finish at {self.end_time}'
                self.__init__()
                logger.error(f'pfm: {ret}')
                return ret
            else:
                return None
        else:
            return None
    def done(self, fname, overwrite=False):
        '''
            return None means success
            else returns an error string
        '''
        if fname == self.fname:
            try:
                REPO_ROOT = Path('repo')
                update_path = REPO_ROOT / 'updates'
                pkg_found = False
                sig_found = False
                for fpath in update_path.iterdir():
                    if fpath.is_dir:
                        continue
                    if fpath.name == self.fname:
                        pkg_found = fpath
                    elif fpath.name == f'{self.fname}.sig':
                        sig_found = fpath
                if pkg_found and sig_found:
                    try:
                        bash(f'{GPG_VERIFY_CMD} {sig_found} {pkg_found}')
                    except CalledProcessError:
                        print_exc_plus()
                        return 'GPG verify error'
                    else:
                        try:
                            if update(overwrite=overwrite):
                                return None
                        except Exception:
                            print_exc_plus()
                        return 'update error'
                else:
                    return f'file missing: pkg {pkg_found} sig {sig_found}'
                return "unexpected error"
            finally:
                self.__init__()
        else:
            return "Wrong file"
    def is_busy(self):
        return not (self.fname is None)

pfm = pushFm()

def push_start(filename, size):
    pfm.tick()
    return pfm.start(filename, size)

def push_done(filename, overwrite=False):
    return pfm.done(filename, overwrite=overwrite)



# server part

def run(funcname, args=list(), kwargs=dict()):
    if funcname in ('clean', 'regenerate', 'remove',
                    'update', 'push_start', 'push_done'):
        logger.info('running: %s %s %s', funcname, args, kwargs)
        ret = eval(funcname)(*args, **kwargs)
        logger.info('done: %s %s',funcname, ret)
        return ret
    else:
        logger.error('unexpected: %s %s %s',funcname, args, kwargs)
        return False

if __name__ == '__main__':
    while True:
        try:
            with Listener(REPOD_BIND_ADDRESS, authkey=REPOD_BIND_PASSWD) as listener:
                with listener.accept() as conn:
                    logger.info('connection accepted from %s', listener.last_accepted)
                    myrecv = conn.recv()
                    if type(myrecv) is list and len(myrecv) == 3:
                        (funcname, args, kwargs) = myrecv
                        funcname = str(funcname)
                        conn.send(run(funcname, args=args, kwargs=kwargs))
        except Exception:
            print_exc_plus()
        except KeyboardInterrupt:
            logger.info('KeyboardInterrupt')
            print_exc_plus()
            break
