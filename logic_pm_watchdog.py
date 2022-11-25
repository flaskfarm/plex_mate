# -*- coding: utf-8 -*-
#########################################################
# python
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime

# third-party
import requests
import xmltodict
from flask import jsonify, redirect, render_template, request
# sjva 공용
from framework import (SystemModelSetting, Util, app, celery, db, path_data,
                       scheduler, socketio)
from plugin import LogicModuleBase, default_route_socketio
from tool_base import ToolBaseFile, ToolSubprocess, d

# 패키지
from .plugin import P

logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting
name = 'watchdog'

from .logic_pm_watchdog_list import LogicPMWatchdogList
from .logic_pm_watchdog_setting import LogicPMWatchdogSetting
from .plex_db import PlexDBHandle
from .plex_web import PlexWebHandle
from .task_pm_base import Task

#########################################################

class LogicPMWatchdog(LogicModuleBase):
    db_default = None

    def __init__(self, P):
        super(LogicPMWatchdog, self).__init__(P, 'setting')
        self.name = name
        self.sub_list = {
            'setting' : LogicPMWatchdogSetting(P, self, 'setting'),
            'list' : LogicPMWatchdogList(P, self, 'list'),
        }

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name
        arg['sub2'] = sub 
        try:
            if sub == 'setting':
                arg['is_include'] = scheduler.is_include(self.sub_list[sub].get_scheduler_name())
                arg['is_running'] = scheduler.is_running(self.sub_list[sub].get_scheduler_name())
            return render_template(f'{package_name}_{name}_{sub}.html', arg=arg)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return render_template('sample.html', title=f"{package_name}/{name}/{sub}")
