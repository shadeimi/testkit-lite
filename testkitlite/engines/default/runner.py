#!/usr/bin/python
#
# Copyright (C) 2012 Intel Corporation
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
# Authors:
#              Zhang, Huihui <huihuix.zhang@intel.com>
#              Wendong,Sui  <weidongx.sun@intel.com>

import os
import platform
import time
from datetime import datetime
from shutil import copyfile
import xml.etree.ElementTree as etree
import ConfigParser
from xml.dom import minidom
from tempfile import mktemp
from testkitlite.common.str2 import *
from testkitlite.common.autoexec import shell_exec
from testkitlite.common.killall import killall
from shutil import move
from os import remove
import re
import subprocess

_j = os.path.join
_d = os.path.dirname
_b = os.path.basename
_e = os.path.exists
_abs = os.path.abspath

class TRunner:
    """
    Parse the testdefinition.xml files.
    Apply filter for each run.
    Conduct tests execution.
    """
    def __init__(self):
        # dryrun
        self.bdryrun = False
        # result file
        self.resultfile = None
        # external test    
        self.external_test = None
        # filter rules
        self.filter_rules = None
        self.fullscreen = False
        self.resultfiles = set()
        self.webapi_merge_status = {}
        self.core_auto_files = []
        self.core_manual_files = []
        self.core_manual_flag = 0
        self.testsuite_dict = {}
        self.exe_sequence = []
        self.testresult_dict = {"pass" : 0, "fail" : 0, "block" : 0, "not_run" : 0}
        self.log = None

    def set_pid_log(self, pid_log):
        self.pid_log = pid_log

    def set_dryrun(self, bdryrun):
        self.bdryrun = bdryrun

    def set_resultfile(self, resultfile):
        self.resultfile = resultfile

    def set_external_test(self, exttest):
        self.external_test = exttest

    def add_filter_rules(self, **kargs):
        """
        kargs:  key:values - "":["",]
        """
        self.filter_rules = kargs

    def set_fullscreen(self, state):
        self.fullscreen = state

    def prepare_run(self, testxmlfile, resultdir=None):
        """
        testxmlfile: target testxml file
        execdir and resultdir: should be the absolute path since TRunner
        is the common lib
        """
        # resultdir is set to current directory by default
        if not resultdir:
            resultdir = os.getcwd()
        ok = True
        if ok:
            try:
                filename = testxmlfile
                filename = os.path.splitext(filename)[0]
                if platform.system() == "Linux":
                    filename = filename.split('/')[3]
                else:
                    filename = filename.split('\\')[-2]
                if self.filter_rules["execution_type"] == ["manual"]:
                    resultfile = "%s.manual.xml" % filename
                else:
                    resultfile = "%s.auto.xml" % filename
                resultfile = _j(resultdir, resultfile)
                if not _e(resultdir):
                    os.mkdir(resultdir)
                print "[ analysis test xml file: %s ]" % resultfile
                try:
                    ep = etree.parse(testxmlfile)
                    suiteparent = ep.getroot()
                    no_test_definition = 1
                    for tf in ep.getiterator('test_definition'):
                        no_test_definition = 0
                    if no_test_definition:
                        suiteparent = etree.Element('test_definition')
                        suiteparent.tail = "\n"
                        for suite in ep.getiterator('suite'):
                            suite.tail = "\n"
                            suiteparent.append(suite)
                    self.apply_filter(suiteparent)
                    try:
                        with open(resultfile, 'w') as output:
                            tree = etree.ElementTree(element=suiteparent)
                            tree.write(output)
                    except IOError, e:
                        print "[ create filtered result file: %s failed, error: %s ]" % (resultfile, e)
                except Exception, e:
                    print e
                    return False
                casefind = etree.parse(resultfile).getiterator('testcase')
                if casefind:
                    file = "%s" % _b(resultfile)
                    file = os.path.splitext(file)[0]
                    testsuite_dict_value_list = []
                    testsuite_dict_add_flag = 0
                    execute_suite_one_way = 1
                    if self.external_test:
                        parser = etree.parse(resultfile)
                        no_wrtlauncher = 1
                        suite_total_count = 0 
                        suite_wrt_launcher_count = 0
                        for tsuite in parser.getiterator('suite'):
                            suite_total_count += 1
                            if tsuite.get('launcher'):
                                if not tsuite.get('launcher').find('WRTLauncher'):
                                    no_wrtlauncher = 0
                                    suite_wrt_launcher_count += 1
                        if no_wrtlauncher:
                            if self.filter_rules["execution_type"] == ["auto"]:
                                self.core_auto_files.append(resultfile)
                            else:
                                self.core_manual_files.append(resultfile)
                        elif suite_total_count == suite_wrt_launcher_count:
                            testsuite_dict_value_list.append(resultfile) 
                            testsuite_dict_add_flag = 1
                            self.exe_sequence.append(file)
                            totalfile = os.path.splitext(resultfile)[0]
                            totalfile = os.path.splitext(totalfile)[0]
                            totalfile = os.path.splitext(totalfile)[0]
                            totalfile = "%s.total" % totalfile
                            totalfile = "%s.xml" % totalfile
                            self.webapi_merge_status[totalfile] = 0
                        else:
                            filename_diff = 1
                            execute_suite_one_way = 0
                            for tsuite in parser.getiterator('suite'):
                                root = etree.Element('test_definition')
                                suitefilename = os.path.splitext(resultfile)[0]
                                suitefilename += ".%s.xml" % filename_diff
                                suitefilename = _j(resultdir, suitefilename)
                                tsuite.tail = "\n"
                                root.append(tsuite)
                                try:
                                    with open(suitefilename, 'w') as output:
                                        tree = etree.ElementTree(element=root)
                                        tree.write(output)
                                except IOError, e:
                                    print "[ create filtered result file: %s failed, error: %s ]" % (suitefilename, e)
                                case_suite_find = etree.parse(suitefilename).getiterator('testcase')
                                if case_suite_find:
                                    if tsuite.get('launcher'):
                                        if tsuite.get('launcher').find('WRTLauncher'):
                                            if self.filter_rules["execution_type"] == ["auto"]:
                                                self.core_auto_files.append(suitefilename)
                                            else:
                                                self.core_manual_files.append(suitefilename)
                                            self.resultfiles.add(suitefilename)
                                        else:
                                            testsuite_dict_value_list.append(suitefilename) 
                                            if testsuite_dict_add_flag == 0:
                                                self.exe_sequence.append(file)
                                            testsuite_dict_add_flag = 1
                                            self.resultfiles.add(suitefilename)
                                            totalfile = os.path.splitext(suitefilename)[0]
                                            totalfile = os.path.splitext(totalfile)[0]
                                            totalfile = os.path.splitext(totalfile)[0]
                                            totalfile = "%s.total" % totalfile
                                            totalfile = "%s.xml" % totalfile
                                            self.webapi_merge_status[totalfile] = 0
                                    else:
                                        if self.filter_rules["execution_type"] == ["auto"]:
                                            self.core_auto_files.append(suitefilename)
                                        else:
                                            self.core_manual_files.append(suitefilename)
                                        self.resultfiles.add(suitefilename)
                                filename_diff += 1
                        if testsuite_dict_add_flag:
                            self.testsuite_dict[file] = testsuite_dict_value_list 
                    else:
                        if self.filter_rules["execution_type"] == ["auto"]:
                            self.core_auto_files.append(resultfile)
                        else:
                            self.core_manual_files.append(resultfile)
                    if execute_suite_one_way:
                        self.resultfiles.add(resultfile)
                        
            except Exception, e:
                print e
                ok &= False
        return ok

    def run_and_merge_resultfile(self, start_time, latest_dir):
        # run core auto cases
        for core_auto_files in self.core_auto_files:
            temp = os.path.splitext(core_auto_files)[0]
            temp = os.path.splitext(temp)[0]
            temp = os.path.splitext(temp)[0]
            
            if self.log:
                self.log = os.path.splitext(self.log)[0]
                self.log = os.path.splitext(self.log)[0]
                self.log = os.path.splitext(self.log)[0]
            if self.log != temp:
                print "[ testing xml: %s.auto.xml ]" % _abs(temp)
            self.log = core_auto_files
            self.execute(core_auto_files, core_auto_files)
            
        # run webAPI cases
        webapi_result = _j(latest_dir, "webapi-result.total.xml")
        if self.exe_sequence:
            self.execute_external_test(self.testsuite_dict, self.exe_sequence, webapi_result)
        
        # run core manual cases
        self.log = None
        for core_manual_files in self.core_manual_files:
            temp = os.path.splitext(core_manual_files)[0]
            temp = os.path.splitext(temp)[0]
            temp = os.path.splitext(temp)[0]
            
            if self.log:
                self.log = os.path.splitext(self.log)[0]
                self.log = os.path.splitext(self.log)[0]
                self.log = os.path.splitext(self.log)[0]
            if self.log != temp:
                print "[ testing xml: %s.manual.xml ]" % _abs(temp)
            self.log = core_manual_files
            self.execute(core_manual_files, core_manual_files)
            
        mergefile = mktemp(suffix='.xml', prefix='tests.', dir=latest_dir)
        mergefile = os.path.splitext(mergefile)[0]
        mergefile = os.path.splitext(mergefile)[0]
        mergefile = "%s.result" % _b(mergefile)
        mergefile = "%s.xml" % mergefile
        mergefile = _j(latest_dir, mergefile)
        end_time = datetime.today().strftime("%Y-%m-%d_%H_%M_%S")
        print "[ test complete at time: %s ]" % end_time
        print "[ start merging test result xml files, this might take some time, please wait ]"
        print "[ merge result files into %s ]" % mergefile
        root = etree.Element('test_definition')
        root.tail = "\n"
        totals = set()
        # create core and webapi set
        resultfiles_core = set()
        for auto_file in self.core_auto_files:
            resultfiles_core.add(auto_file)
        for manual_file in self.core_manual_files:
            resultfiles_core.add(manual_file)
        resultfiles_webapi = self.resultfiles
        for resultfile_core in resultfiles_core:
            resultfiles_webapi.discard(resultfile_core)
        # merge core result files
        for resultfile_core in resultfiles_core:
            totalfile = os.path.splitext(resultfile_core)[0]
            totalfile = os.path.splitext(totalfile)[0]
            totalfile = os.path.splitext(totalfile)[0]
            totalfile = "%s.total" % totalfile
            totalfile = "%s.xml" % totalfile
            total_xml = etree.parse(totalfile)
            
            result_xml = etree.parse(resultfile_core)
            print "|--[ merge webapi result file: %s ]" % resultfile_core
                    
            for total_suite in total_xml.getiterator('suite'):
                for total_set in total_suite.getiterator('set'):
                    for result_suite in result_xml.getiterator('suite'):
                        for result_set in result_suite.getiterator('set'):
                            # when total xml and result xml have same suite name and set name
                            if result_set.get('name') == total_set.get('name') and result_suite.get('name') == total_suite.get('name'):
                                # set cases that doesn't have result in result set to N/A
                                # append cases from result set to total set
                                result_case_iterator = result_set.getiterator('testcase')
                                if result_case_iterator:
                                    print "`----[ suite: %s, set: %s, time: %s ]" % (result_suite.get('name'), result_set.get('name'), datetime.today().strftime("%Y-%m-%d_%H_%M_%S"))
                                    for result_case in result_case_iterator:
                                        try:
                                            if not result_case.get('result'):
                                                result_case.set('result', 'N/A')
                                            if result_case.get('result') == "PASS":
                                                self.testresult_dict["pass"] += 1
                                            if result_case.get('result') == "FAIL":
                                                self.testresult_dict["fail"] += 1
                                            if result_case.get('result') == "BLOCK":
                                                self.testresult_dict["block"] += 1
                                            if result_case.get('result') == "N/A":
                                                self.testresult_dict["not_run"] += 1
                                            total_set.append(result_case)
                                        except Exception, e:
                                            print "[ fail to append %s, error: %s ]" % (result_case.get('id'), e)
            total_xml.write(totalfile)
            totals.add(totalfile)
        # merge webapi result files
        for resultfile_webapi in resultfiles_webapi:
            totalfile = os.path.splitext(resultfile_webapi)[0]
            totalfile = os.path.splitext(totalfile)[0]
            totalfile = os.path.splitext(totalfile)[0]
            totalfile = "%s.total" % totalfile
            totalfile = "%s.xml" % totalfile
            total_xml = etree.parse(totalfile)
            
            isNotMerged = True
            if self.webapi_merge_status[totalfile] == 1:
                isNotMerged = False
            else:
                self.webapi_merge_status[totalfile] = 1
            if isNotMerged:
                try:
                    result_xml = etree.parse(webapi_result)
                    print "|--[ merge webapi result file: %s ]" % webapi_result
                except Exception, e:
                    print "|--[ merge result file: %s ]" % resultfile_webapi
                    result_xml = etree.parse(resultfile_webapi)
                    print "[ Error: %s is not generated by http server, set all results to N/A ]\n" % webapi_result
                    self.webapi_merge_status[totalfile] = 0
                    
                for total_suite in total_xml.getiterator('suite'):
                    for total_set in total_suite.getiterator('set'):
                        for result_suite in result_xml.getiterator('suite'):
                            for result_set in result_suite.getiterator('set'):
                                # when total xml and result xml have same suite name and set name
                                if result_set.get('name') == total_set.get('name') and result_suite.get('name') == total_suite.get('name'):
                                    # set cases that doesn't have result in result set to N/A
                                    # append cases from result set to total set
                                    result_case_iterator = result_set.getiterator('testcase')
                                    if result_case_iterator:
                                        print "`----[ suite: %s, set: %s, time: %s ]" % (result_suite.get('name'), result_set.get('name'), datetime.today().strftime("%Y-%m-%d_%H_%M_%S"))
                                        for result_case in result_case_iterator:
                                            try:
                                                if not result_case.get('result'):
                                                    result_case.set('result', 'N/A')
                                                if result_case.get('result') == "PASS":
                                                    self.testresult_dict["pass"] += 1
                                                if result_case.get('result') == "FAIL":
                                                    self.testresult_dict["fail"] += 1
                                                if result_case.get('result') == "BLOCK":
                                                    self.testresult_dict["block"] += 1
                                                if result_case.get('result') == "N/A":
                                                    self.testresult_dict["not_run"] += 1
                                                total_set.append(result_case)
                                            except Exception, e:
                                                print "[ fail to append %s, error: %s ]" % (result_case.get('id'), e)
                total_xml.write(totalfile)
                totals.add(totalfile)
        for total in totals:
            result_xml = etree.parse(total)
            for suite in result_xml.getiterator('suite'):
                suite.tail = "\n"
                root.append(suite)
        try:
            with open(mergefile, 'w') as output:
                tree = etree.ElementTree(element=root)
                tree.write(output)
        except IOError, e:
            print "[ merge result file failed, error: %s ]" % e
        # report the result using xml mode
        print "[ generate result xml: %s ]" % mergefile
        if self.core_manual_flag:
            print "[ all results for core manual cases are N/A, the result file is at %s ]" % mergefile
        print "[ test summary ]"
        total_case_number = int(self.testresult_dict["pass"]) + int(self.testresult_dict["fail"]) + int(self.testresult_dict["block"]) + int(self.testresult_dict["not_run"])
        print "  [ total case number: %s ]" % (total_case_number)
        if total_case_number == 0:
            print "[Warning: found 0 case from the result files, if it's not right, please check the test xml files, or the filter values ]"
        else:
            print "  [ pass rate: %.2f%% ]" % (int(self.testresult_dict["pass"]) * 100 / int(total_case_number))
            print "  [ PASS case number: %s ]" % self.testresult_dict["pass"]
            print "  [ FAIL case number: %s ]" % self.testresult_dict["fail"]
            print "  [ BLOCK case number: %s ]" % self.testresult_dict["block"]
            print "  [ N/A case number: %s ]" % self.testresult_dict["not_run"]
        print "[ merge complete, write to the result file, this might take some time, please wait ]"
        
        ep = etree.parse(mergefile)
        rt = ep.getroot()
        device_info = self.get_device_info()
        environment = etree.Element('environment')
        environment.attrib['device_id'] = "Empty device_id"
        environment.attrib['device_model'] = device_info["device_model"]
        environment.attrib['device_name'] = device_info["device_name"]
        environment.attrib['firmware_version'] = "Empty firmware_version"
        environment.attrib['host'] = "Empty host"
        environment.attrib['os_version'] = device_info["os_version"]
        environment.attrib['resolution'] = device_info["resolution"]
        environment.attrib['screen_size'] = device_info["screen_size"]
        other = etree.Element('other')
        other.text = "Here is a String for testing"
        environment.append(other)
        environment.tail = "\n"
        summary = etree.Element('summary')
        summary.attrib['test_plan_name'] = "Empty test_plan_name"
        start_at = etree.Element('start_at')
        start_at.text = start_time
        end_at = etree.Element('end_at')
        end_at.text = end_time
        summary.append(start_at)
        summary.append(end_at)
        summary.tail = "\n  "
        rt.insert(0, summary)
        rt.insert(0, environment)
        # add XSL support to testkit-lite
        DECLARATION = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="testresult.xsl"?>\n"""
        with open(mergefile, 'w') as output:
            output.write(DECLARATION)
            ep.write(output, xml_declaration=False, encoding='utf-8')
        # change &lt;![CDATA[]]&gt; to <![CDATA[]]>
        self.replace_cdata(mergefile)
        
        if self.resultfile:
                copyfile(mergefile, self.resultfile)

    def get_device_info(self):
        device_info = {}
        resolution_str = "Empty resolution"
        screen_size_str = "Empty screen_size"
        device_model_str = "Empty device_model"
        device_name_str = "Empty device_name"
        os_version_str = ""
        # get resolution and screen size
        fi, fo, fe = os.popen3("xrandr")
        for line in fo.readlines():
            pattern = re.compile('connected (\d+)x(\d+).* (\d+mm) x (\d+mm)')
            match = pattern.search(line)
            if match:
                resolution_str = "%s x %s" % (match.group(1), match.group(2))
                screen_size_str = "%s x %s" % (match.group(3), match.group(4))
        # get architecture
        fi, fo, fe = os.popen3("uname -m")
        device_model_str_tmp = fo.readline()
        if len(device_model_str_tmp) > 1:
            device_model_str = device_model_str_tmp[0:-1]
        # get hostname
        fi, fo, fe = os.popen3("uname -n")
        device_name_str_tmp = fo.readline()
        if len(device_name_str_tmp) > 1:
            device_name_str = device_name_str_tmp[0:-1]
        # get os version
        fi, fo, fe = os.popen3("cat /etc/issue")
        for line in fo.readlines():
            if len(line) > 1:
                os_version_str = "%s %s" % (os_version_str, line)
        os_version_str = os_version_str[0:-1]
        
        device_info["resolution"] = resolution_str
        device_info["screen_size"] = screen_size_str
        device_info["device_model"] = device_model_str
        device_info["device_name"] = device_name_str
        device_info["os_version"] = os_version_str
        
        return device_info

    def pretty_print(self, ep, resultfile):
        rawstr = etree.tostring(ep.getroot(), 'utf-8')
        t = minidom.parseString(rawstr)
        open(resultfile, 'w+').write(t.toprettyxml(indent="  "))

    def execute_external_test(self, testsuite, exe_sequence, resultfile):
        """Run external test"""
        from testkithttpd import startup
        if self.bdryrun:
            print "[ WRTLauncher mode does not support dryrun ]"
            return True
        # start http server in here
        try:
            parameters = {}
            parameters.setdefault("pid_log", self.pid_log)
            parameters.setdefault("testsuite", testsuite)
            parameters.setdefault("exe_sequence", exe_sequence)
            parameters.setdefault("client_command", self.external_test)
            if self.fullscreen:
                parameters.setdefault("hidestatus", "1")
            else:
                parameters.setdefault("hidestatus", "0")
            parameters.setdefault("resultfile", resultfile)
            # kill existing http server
            http_server_pid = "none"
            fi, fo, fe = os.popen3("netstat -tpa | grep 8000")
            for line in fo.readlines():
                pattern = re.compile('([0-9]*)\/python')
                match = pattern.search(line)
                if match:
                    http_server_pid = match.group(1)
                    print "[ kill existing http server, pid: %s ]" % http_server_pid
                    killall(http_server_pid)
            if http_server_pid == "none":
                print "[ start new http server ]"
            else:
                print "[ start new http server in 3 seconds ]"
                time.sleep(3)
            startup(parameters)
        except Exception, e:
            print "[ Error: fail to start http server, error: %s ]\n" % e
        return True

    def apply_filter(self, rt):
        def case_check(tc):
            rules = self.filter_rules
            for key in rules.iterkeys():
                if key in ["suite", "set"]:
                    continue
                # Check attribute
                t_val = tc.get(key)
                if t_val:
                    if not t_val in rules[key]:
                        return False
                else:
                    # Check sub-element
                    items = tc.getiterator(key)
                    if items: 
                        t_val = []
                        for i in items:
                            t_val.append(i.text)
                        if len(set(rules[key]) & set(t_val)) == 0:
                            return False
            return True
        
        rules = self.filter_rules
        for tsuite in rt.getiterator('suite'):
            if rules.get('suite'):
                if tsuite.get('name') not in rules['suite']:
                    rt.remove(tsuite)
            for tset in tsuite.getiterator('set'):
                if rules.get('set'):
                    if tset.get('name') not in rules['set']:
                        tsuite.remove(tset)
                       
        for tset in rt.getiterator('set'):
            for tc in tset.getiterator('testcase'):
                if not case_check(tc):
                    tset.remove(tc)

    def execute(self, testxmlfile, resultfile):
        def exec_testcase(case):
            ok = True
            rt_code, stdout, stderr = None, None, None
            
            """ Handle manual test """
            if case.get('execution_type', '') == 'manual':
                case.set('result', 'N/A')
                self.core_manual_flag = 1
                try:
                    for attr in case.attrib:
                        print "    %s: %s" % (attr, case.get(attr))
                    notes = case.find("description/notes")
                    print "    notes: %s" % notes.text
                    descs = case.getiterator("step_desc")
                    for desc in descs:
                        print "    desc: %s" % desc.text
                except:
                    pass
                return ok
                
            case.set('result', 'BLOCK')
            testentry_elm = case.find('description/test_script_entry')
            expected_result = testentry_elm.get('test_script_expected_result', '0')
            # Construct result info node
            resinfo_elm = etree.Element('result_info')
            res_elm = etree.Element('actual_result')
            start_elm = etree.Element('start')
            end_elm = etree.Element('end')
            stdout_elm = etree.Element('stdout')
            stderr_elm = etree.Element('stderr')
            resinfo_elm.append(res_elm)
            resinfo_elm.append(start_elm)
            resinfo_elm.append(end_elm)
            resinfo_elm.append(stdout_elm)
            resinfo_elm.append(stderr_elm)
            
            case.append(resinfo_elm)
            
            start_elm.text = datetime.today().strftime("%Y-%m-%d_%H_%M_%S")
            if self.bdryrun:
                return_code, stderr, stdout = "0", "Dryrun error info", "Dryrun output"
            else:
                if testentry_elm.get('timeout'):
                    return_code, stderr, stdout = \
                    shell_exec(testentry_elm.text, "no_log", str2number(testentry_elm.get('timeout')), True)
                else:
                    return_code, stderr, stdout = \
                    shell_exec(testentry_elm.text, "no_log", 90, True)
                    
            # convert all return code to string in order to compare test result
            if return_code is None:
                res_elm.text = 'None'
            else:
                res_elm.text = str(return_code)
            stdout_elm.text = stdout
            stderr_elm.text = stderr
            # record endtime
            end_elm.text = datetime.today().strftime("%Y-%m-%d_%H_%M_%S")
            
            if return_code is not None:
                if expected_result == res_elm.text:
                    case.set('result', 'PASS')
                else:
                    case.set('result', 'FAIL')
            # Check performance test
            measures = case.getiterator('measurement')
            for m in measures:
                ind = m.get('name')
                fname = m.get('file')
                if fname and _e(fname):
                    try:
                        config = ConfigParser.ConfigParser()
                        config.read(fname)
                        val = config.get(ind, 'value')
                        m.set('value', val)
                    except Exception, e:
                        print e
                    
            return ok
        # Go
        try:
            ep = etree.parse(testxmlfile)
            rt = ep.getroot()
            for tsuite in rt.getiterator('suite'):
                for tcaselog in tsuite.getiterator('testcase'):
                    if tcaselog.get('execution_type') == 'manual':
                        print "[suite] execute manual suite:\nTestSuite: %s" % tsuite.get('name')
                        break
                    else:
                        print "[suite] execute suite:\nTestSuite: %s" % tsuite.get('name')
                        break
                for tset in tsuite.getiterator('set'):
                    print "[set] execute set:\nTestSet: %s" % tset.get('name')
                    for tc in tset.getiterator('testcase'):
                        print "\n[case] execute case:\nTestCase: %s" % tc.get("id")
                        exec_testcase(tc)
            ep.write(resultfile)
            return True
        except Exception, e:
            print "[ Error: fail to run core test case, error: %s ]\n" % e
            return False

    def replace_cdata(self, file_name):
        abs_path = mktemp()
        new_file = open(abs_path, 'w')
        old_file = open(file_name)
        for line in old_file:
            line_temp = line.replace('&lt;![CDATA', '<![CDATA')
            new_file.write(line_temp.replace(']]&gt;', ']]>'))
        new_file.close()
        old_file.close()
        remove(file_name)
        move(abs_path, file_name)