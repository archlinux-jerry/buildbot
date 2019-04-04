#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repod.py: Automatic management tool for an arch repo.
# This file is part of Buildbot by JerryXiao

import logging
from multiprocessing.connection import Client
from time import sleep

from config import REPOD_BIND_ADDRESS, REPOD_BIND_PASSWD
from utils import print_exc_plus

logger = logging.getLogger(__name__)

def ping(funcname, args=list(), kwargs=dict(), retries=0):
    try:
        logger.info('client: %s %s %s',funcname, args, kwargs)
        with Client(REPOD_BIND_ADDRESS, authkey=REPOD_BIND_PASSWD) as conn:
            conn.send([funcname, args, kwargs])
            return conn.recv()
    except ConnectionRefusedError:
        if retries <= 10:
            logger.info("Server refused, retry after 60s")
            sleep(60)
            return ping(funcname, args=args, kwargs=kwargs, retries=retries+1)
        else:
            logger.error("Server refused")
            return False
    except EOFError:
        logger.error('Internal server error')
        return False
    except Exception:
        print_exc_plus()

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger.info('result: %s', ping('push_files', args=('aaa', 1)))
    logger.info('result: %s', ping('add_files', args=('aaa',)))
    #logger.info('result: %s', ping('update'))
