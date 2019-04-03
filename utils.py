#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import logging
from time import time
import re
from threading import Thread, Lock
import sys
import traceback

from config import PKG_COMPRESSION

logger = logging.getLogger(name='utils')

def background(func):
    def wrapped(*args, **kwargs):
        tr = Thread(target=func, args=args, kwargs=kwargs)
        tr.daemon = True
        tr.start()
        return tr
    return wrapped

def bash(cmdline, **kwargs):
    assert type(cmdline) is str
    logger.info(f'bash: {cmdline}')
    return(run_cmd(['/bin/bash', '-x', '-e', '-c', cmdline], **kwargs))

def long_bash(cmdline, hours=2):
    assert type(hours) is int and hours >= 1
    logger.info(f'longbash{hours}: {cmdline}')
    return bash(cmdline, keepalive=True, KEEPALIVE_TIMEOUT=60, RUN_CMD_TIMEOUT=hours*60*60)

def run_cmd(cmd, keepalive=False, KEEPALIVE_TIMEOUT=30, RUN_CMD_TIMEOUT=60):
    RUN_CMD_LOOP_TIME = KEEPALIVE_TIMEOUT - 1 if KEEPALIVE_TIMEOUT >= 10 else 5
    stopped = False
    last_read = [int(time()), ""]
    output = list()
    stdout_lock = Lock()
    @background
    def check_stdout(stdout):
        nonlocal stopped, last_read, output
        stdout_lock.acquire()
        last_read_time = int(time())
        while stopped is False:
            line = stdout.readline(4096)
            last_read_time = int(time())
            logger.debug(line)
            output.append(line)
            last_read[0] = last_read_time
            last_read[1] = line
        stdout_lock.release()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, encoding='utf-8')
    check_stdout(p.stdout)
    process_start = int(time())
    while True:
        try:
            p.wait(timeout=RUN_CMD_LOOP_TIME)
        except subprocess.TimeoutExpired:
            time_passed = int(time()) - last_read[0]
            if time_passed >= KEEPALIVE_TIMEOUT*2:
                logger.info('Timeout expired. No action.')
                output.append('+ Buildbot: Timeout expired. No action.\n')
            elif time_passed >= KEEPALIVE_TIMEOUT:
                if keepalive:
                    logger.info('Timeout expired, writing nl')
                    output.append('+ Buildbot: Timeout expired, writing nl\n')
                    p.stdin.write('\n')
                    p.stdin.flush()
                else:
                    logger.info('Timeout expired, not writing nl')
                    output.append('+ Buildbot: Timeout expired, not writing nl\n')
            if int(time()) - process_start >= RUN_CMD_TIMEOUT:
                stopped = True
                logger.error('Process timeout expired, terminating.')
                output.append('+ Buildbot: Process timeout expired, terminating.\n')
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.error('Cannot terminate, killing.')
                    output.append('+ Buildbot: Cannot terminate, killing.\n')
                    p.kill()
                break
        else:
            stopped = True
            break
    code = p.returncode

    stdout_lock.acquire(10)
    outstr = ''.join(output)

    if code != 0:
        raise subprocess.CalledProcessError(code, cmd, outstr)
    return outstr

class Pkg:
    def __init__(self, pkgname, pkgver, pkgrel, arch):
        self.pkgname = pkgname
        self.pkgver = pkgver
        self.pkgrel = pkgrel
        self.arch = arch

def get_pkg_details_from_name(name):
    assert type(name) is str
    if name.endswith(f'pkg.tar.{PKG_COMPRESSION}'):
        m = re.match(r'(.+)-([^-]+)-([^-]+)-([^-]+)\.pkg\.tar\.\w+', name)
        assert m and m.groups() and len(m.groups()) == 4
        (pkgname, pkgver, pkgrel, arch) = m.groups()
        return Pkg(pkgname, pkgver, pkgrel, arch)

def print_exc_plus():
    """
    Print the usual traceback information, followed by a listing of all the
    local variables in each frame.
    from Python Cookbook by David Ascher, Alex Martelli
    """
    tb = sys.exc_info()[2]
    while True:
        if not tb.tb_next:
            break
        tb = tb.tb_next
    stack = []
    f = tb.tb_frame
    while f:
        stack.append(f)
        f = f.f_back
    stack.reverse()
    traceback.print_exc()
    print("Locals by frame, innermost last")
    for frame in stack:
        print("Frame %s in %s at line %s" % (frame.f_code.co_name,
                                             frame.f_code.co_filename,
                                             frame.f_lineno))
        for key, value in frame.f_locals.items(  ):
            print("\t%20s = " % key, end=' ')
            # We have to be VERY careful not to cause a new error in our error
            # printer! Calling str(  ) on an unknown object could cause an
            # error we don't want, so we must use try/except to catch it --
            # we can't stop it from happening, but we can and should
            # stop it from propagating if it does happen!
            try:
                print(value)
            except:
                print("<ERROR WHILE PRINTING VALUE>")

