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

from shared_vars import PKG_SUFFIX, PKG_SIG_SUFFIX



from repo import _clean_archive as clean, \
                 _regenerate as regenerate, \
                 _remove as remove, \
                 _update as update

from utils import bash, configure_logger, print_exc_plus

abspath=os.path.abspath(__file__)
abspath=os.path.dirname(abspath)
os.chdir(abspath)

logger = logging.getLogger('buildbot')
configure_logger(logger, logfile='repod.log', rotate_size=1024*1024*10, enable_notify=True)

class pushFm:
    def __init__(self):
        self.fnames = list()
        self.size = None
        self.sizes = None
        self.start_time = None
        self.end_time = None
    def start(self, fnames, sizes):
        '''
            sizes is list in MB
            returns -1 when busy
        '''
        if self.is_busy():
            return -1
        self.fnames = fnames
        self.start_time = time()
        self.sizes = sizes
        size = 0
        for s in sizes:
            size += s
        self.size = size
        def get_timeout(size):
            if size <= 7.5:
                timeout = 120
            else:
                timeout = size / (REPO_PUSH_BANDWIDTH / 8) * 2
            return timeout
        timeouts = [get_timeout(s) for s in sizes]
        self.end_time = self.start_time + get_timeout(self.size)
        return timeouts
    def tick(self):
        '''
            return None means success
            else returns an error string
        '''
        if self.is_busy():
            if time() > self.end_time:
                ret = f'files {self.fnames} are supposed to finish at {self.end_time}'
                self.__init__()
                logger.error(f'tick: {ret}')
                return ret
            else:
                return None
        else:
            return None
    def fail(self, tfname):
        update_path = Path('updates')
        if tfname in self.fnames:
            for fname in self.fnames:
                pkg = update_path / fname
                sig = update_path / f'{fname}.sig'
                for f in (pkg, sig):
                    if f.exists():
                        try:
                            f.unlink()
                        except Exception:
                            logger.warning(f'unable to remove {f.name}')
            self.__init__()
            return None
        else:
            return "Wrong file"
    def done(self, fnames, overwrite=False):
        '''
            return None means success
            else returns an error string
        '''
        if [f for f in fnames if not (f.endswith(PKG_SUFFIX) or f.endswith(PKG_SIG_SUFFIX))]:
            return "file to upload are garbage"
        filter_sig = lambda fnames:[fname for fname in fnames if not fname.endswith(PKG_SIG_SUFFIX)]
        if sorted(filter_sig(fnames)) == sorted(filter_sig(self.fnames)):
            try:
                update_path = Path('updates')
                for pkgfname in filter_sig(fnames):
                    pkg_found = False
                    sig_found = False
                    for fpath in update_path.iterdir():
                        if fpath.is_dir():
                            continue
                        if fpath.name == pkgfname:
                            pkg_found = fpath
                        elif fpath.name == f'{pkgfname}.sig':
                            sig_found = fpath
                    if pkg_found and sig_found:
                        try:
                            bash(f'{GPG_VERIFY_CMD} {sig_found} {pkg_found}')
                        except CalledProcessError:
                            ret = f'{pkg_found} GPG verify error'
                            logger.error(ret)
                            print_exc_plus()
                            return ret
                        else:
                            try:
                                if update(overwrite=overwrite):
                                    continue
                                else:
                                    raise RuntimeError('update return false')
                            except Exception:
                                print_exc_plus()
                                return f'{pkg_found} update error'
                    else:
                        return f'file missing: pkg {pkg_found} sig {sig_found}'
                    return "unexpected error"
                else:
                    # success
                    return None
            finally:
                self.__init__()
        else:
            return "Wrong file"
    def is_busy(self):
        return bool(self.fnames)

pfm = pushFm()

def push_start(filenames, sizes):
    pfm.tick()
    return pfm.start(filenames, sizes)

def push_done(filenames, overwrite=False):
    return pfm.done(filenames, overwrite=overwrite)

def push_fail(filename):
    return pfm.fail(filename)

# server part

def run(funcname, args=list(), kwargs=dict()):
    if funcname in ('clean', 'regenerate', 'remove',
                    'update', 'push_start', 'push_done',
                    'push_fail'):
        logger.info('running: %s %s %s', funcname, args, kwargs)
        ret = eval(funcname)(*args, **kwargs)
        logger.info('done: %s %s',funcname, ret)
        return ret
    else:
        logger.error('unexpected: %s %s %s',funcname, args, kwargs)
        return False

if __name__ == '__main__':
    logger.info('Buildbot.repod started.')
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
