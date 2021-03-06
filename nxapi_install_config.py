#!/usr/bin/python

"""
     Copyright (c) 2015 - 2016 World Wide Technology, Inc.
     All rights reserved.

     Revision history:
     30  January 2015  |  1.0 - initial release
     19  Feb     2015  |  1.1 - tested thru ./ansible/hacking/test-module
     11  March   2015  |  1.2 - logic for configuration errors
     28  July    2015  |  1.3 - added license file to project and updated copyright
     25  Sept    2015  |  1.4 - implement HTTPs, ignore comments beginning with ! as well
     27  Sept    2015  |  1.5 - added userid to log file name
     26  Feb     2016  |  2.0 - Ansible 2.0 fix for debug boolean
     09  Mar     2016  |  2.1 - Added better error reporting for requests post command
     27  May     2016  |  2.2 - type="bool" on debug  Ansible 2.1

"""

DOCUMENTATION = '''
---
module: nxapi_install_config
author: Joel W. King, World Wide Technology
version_added: "2.2"
short_description: Load a configuration file into a device running NXOS feature nxapi
description:
    - This module reads a configuration file and uses the nxapi feature to push the configuration
      using the nxapi interface. The module writes a log file to the /tmp directory and imbeds the
      julian date in the file name. For example, this file is for day 50, e.g. /tmp/nxapi_install_config_050.log

 
requirements:
    - Enable the nxapi feature on the Nexus switch(s)
          NEX-9396-A(config)# feature nxapi
 
    - For modules developed under windows, you need to run "dos2unix" so thge shebang line is recognized 

options:
    host:
        description:
            - The IP address or hostname of the nxapi interface
        required: true

    username:
        description:
            - Login username of the nxapi interface
        required: true

    password:
        description:
            - Login password
        required: true

    config_file:
        description:
            - Path to the file containing the nxos configuration data. Any comment lines
              are stripped from the file, as the nxapi feature rejects comments as invalid.
        required: true

    debug:
        description:
            - Debugging output enabled when value set to True
        required: false
'''

EXAMPLES = '''
       
     - name: Generate Nexus configuration files
       template:
        src: "./roles/{{role_path|basename}}/templates/nxapi_template.j2"
        dest: "./roles/{{role_path|basename}}/files/__{{hostname}}.cfg"

     - name: Push configuration to devices
       nxapi_install_config.py:
        config_file: "./roles/{{role_path|basename}}/files/__{{hostname}}.cfg"
        host: "{{host}}"
        username: "{{username}}"
        password: "{{password}}"
        debug: "{{debug}}"

'''

import time
import json
import requests
import logging
import getpass

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

logfilename = 'nxapi_install_config'
logger = logging.getLogger(logfilename)
hdlrObj = logging.FileHandler("/tmp/%s_%s_%s.log" % (logfilename, getpass.getuser(), time.strftime("%j")))
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlrObj.setFormatter(formatter)
logger.addHandler(hdlrObj)

# ---------------------------------------------------------------------------
# CONNECTION
# ---------------------------------------------------------------------------

class Connection(object):
    """
        connection object for Cisco Nexus 9000 / 3000 feature nxapi
    """
    def __init__(self, log_obj, username, password):

        self.debug = False
        self.logger = log_obj
        self.logger.setLevel(logging.INFO)
        self.url = 'https://192.0.2.1/ins'
        self.hostname = 'example.net'
        self.username = username
        self.password = password
        self.header = {'content-type':'application/json-rpc'}
        self.payload = []
        self.changed = False



    def debugging(self):
        " return the debug switch "
        return self.debug



    def set_debug(self, value):
        "set the debug value"
        if value:
            self.debug = True
            self.logger.setLevel(logging.DEBUG)
        self.logger.debug("DEVICE=%s exiting set_debug with self.debug=%s" % (self.get_hostname(), self.debug))



    def get_hostname(self):
        "return the hostname"
        return self.hostname



    def get_changed_flag(self):
        "show commands do not change the configuration, config commands do"
        return self.changed



    def set_changed_flag(self, response):
        """look at all the comand lines, if at least one has None, then
           the configuration was changed"""

        changed = 0
        for cmd in response:
            try:
                if cmd["result"] is None:
                    changed +=1
            except KeyError:
                pass

        if changed:
            self.changed = True



    def check_for_errors(self, rc, response):
        """ for any command line, if we have an error message, there was a problem. Subsequent commands
            will not be executed, that message will be 'Command not ran due to previous failures'
            so once you find and error, return the message of the first error.
        """
        for cmd in response:
            try:
                response = "%s on line %s" % (cmd["error"]["message"], cmd["id"])
                rc = 1
                break
            except KeyError:
                pass
        return rc, response



    def set_url(self, hostname):
        "set the IP address of hostname in the URL "
        self.url = 'https://%s/ins' % hostname
        self.hostname = hostname



    def genericPOST(self):
        """ issues a post request to Nexus nxapi 
            note: the python code example off the sandbox will fail on a ValueError if 
            an incorrect username or password is provided, and not give you a status_code"""

        if self.debugging():
            self.logger.debug("DEVICE=%s entering genericPOST" % self.get_hostname())

        try:
            response = requests.post(self.url,
                                     data=json.dumps(self.payload),
                                     headers=self.header,
                                     verify=False,
                                     auth=(self.username, self.password)) 
        except requests.ConnectionError as e:
            return 1, ("ConnectionError: %s" % e)
        except ValueError as e:
            return 1, ("ValueError: %s" % e)
        else:
            if response.status_code == 200:
                content = json.loads(response.content)
                if type(content) == dict:
                    content = [content]                       # when only one cmd sent, you get a dictionary back, >1, a list
                self.set_changed_flag(content)                # the configuration can be changed even if errors
                return self.check_for_errors(0, content)      # modify rc, response if errors existed.
            else:
                return 1, ("Failed connection, status_code: %s" % response.status_code)



    def load_config_file(self, config_file):
        """ load the config file template into the payload. Each command is a dictionary element of a list"""

        if self.debugging():
            self.logger.debug("DEVICE=%s Entering load_config_file with filename=%s" % (self.get_hostname(),config_file))

        with open(config_file, 'r') as f:
            i = 0
            for line in f:
                line = line.rstrip('\n')                   # remove newline characters
                if line:                                   # line could empty - a blank line,  at this point
                    if line[0] in "#!":                    # ignore comments, lines starting with # or !
                        continue
                else:
                    continue                               # ignore blank lines
                i += 1
                self.payload.append({"jsonrpc": "2.0", "method": "cli", "params": {"cmd": line, "version": 1}, "id": i})
                if self.debugging():
                    self.logger.debug("DEVICE=%s id: %s cmd: %s" % (self.get_hostname(), i, line))



# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():

    module = AnsibleModule(
        argument_spec = dict(
            config_file = dict(required=True),
            host = dict(required=True),
            username = dict(required=True),
            password  = dict(required=True),
            debug = dict(required=False, default=False, type="bool")
         ),
        check_invalid_arguments=False,
        add_file_common_args=True
    )

    switch = Connection(logger, module.params["username"], module.params["password"])
    switch.set_url(module.params["host"])

    try:
        switch.set_debug(module.params["debug"])
    except KeyError:
        pass

    switch.load_config_file(module.params["config_file"])

    code, response = switch.genericPOST()

    if code == 1:
        logger.error('DEVICE=%s STATUS=%s MSG=%s' % (module.params["host"], code, response))
        module.fail_json(msg=response)
    else:
        logger.info('DEVICE=%s STATUS=%s' % (module.params["host"], code))
        module.exit_json(changed=switch.get_changed_flag(), content=response)
    return code


from ansible.module_utils.basic import *
main()


#
# References:
#            Juniper.junos Ansible Modules
#              http://junos-ansible-modules.readthedocs.org/en/1.1.0/
#              https://raw.githubusercontent.com/Juniper/ansible-junos-stdlib/master/library/junos_install_config
#
#            datacenter/nexus9000
#            https://github.com/datacenter/nexus9000/tree/master/nx-os/nxapi
#
#            Cisco Nexus 9000 Series NX-OS Programmability Guide, Release 6.x
#            http://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/programmability/guide/b_Cisco_Nexus_9000_Series_NX-OS_Programmability_Guide.pdf
#
#
#           Developing Modules - 
#           http://docs.ansible.com/developing_modules.html
#           https://github.com/ansible/ansible-modules-core/blob/devel/network/basics/uri.py
#           http://blog.josephkahn.io/articles/ansible-modules/
#           https://groups.google.com/forum/#!forum/ansible-project
#
