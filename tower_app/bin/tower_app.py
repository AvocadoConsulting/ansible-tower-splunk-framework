#!/usr/bin/env python

# Python
import base64
import collections
import json
import os
import urlparse

# Requests
import requests

# Splunk SDK
from splunklib.modularinput import *


class PersistentState(collections.MutableMapping):

    def __init__(self, metadata, input_name):
        self._filename = os.path.join(
            metadata.get('checkpoint_dir', ''),
            '{}.json'.format(base64.urlsafe_b64encode(input_name)),
        )

    def _load(self):
        if os.path.exists(self._filename):
            return json.loads(open(self._filename, 'r').read() or '{}')
        return {}

    def _store(self, data):
        json.dump(data, open(self._filename, 'w'))

    def __iter__(self):
        return iter(self._load())
    
    def __len__(self):
        return len(self._load())

    def __getitem__(self, key):
        return self._load()[key]
    
    def __setitem__(self, key, value):
        data = self._load()
        data[key] = value
        self._store(data)

    def __delitem__(self, key):
        data = self._load()
        del data[key]
        self._store(data)


class TowerAppScript(Script):

    def get_scheme(self):
        scheme = Scheme('Tower app')
        scheme.description = 'Streams events from Ansible Tower'
        scheme.use_external_validation = True
        scheme.use_single_instance = True

        tower_host_argument = Argument('tower_host')
        tower_host_argument.title = 'Tower Host'
        tower_host_argument.data_type = Argument.data_type_string
        tower_host_argument.description = 'Host (and optional port) of Tower server.'
        tower_host_argument.required_on_create = True
        scheme.add_argument(tower_host_argument)

        verify_ssl_argument = Argument('verify_ssl')
        verify_ssl_argument.title = 'Verify SSL?'
        verify_ssl_argument.data_type = Argument.data_type_boolean
        verify_ssl_argument.description = 'Verify SSL cert on Tower server.'
        scheme.add_argument(verify_ssl_argument)

        username_argument = Argument('username')
        username_argument.title = 'Username'
        username_argument.data_type = Argument.data_type_string
        username_argument.description = 'Username to access Tower server.'
        username_argument.required_on_create = True
        scheme.add_argument(username_argument)

        password_argument = Argument('password')
        password_argument.title = 'Password'
        password_argument.data_type = Argument.data_type_string
        password_argument.description = 'Password to access Tower server.'
        password_argument.required_on_create = True
        scheme.add_argument(password_argument)

        return scheme

    def validate_input(self, validation_definition):
        tower_host = validation_definition.parameters['tower_host']
        verify_ssl = False#validation_definition.parameters['verify_ssl']
        username = validation_definition.parameters['username']
        password = validation_definition.parameters['password']
        api_config_url = urlparse.urlunsplit(['https', tower_host, '/api/v1/config/', '', ''])
        response = requests.get(api_config_url, auth=(username, password), verify=bool(verify_ssl))
        response.raise_for_status()
        data = response.json()
        if not 'version' in data:
            raise ValueError('Does not appear to be a Tower server')

    def stream_events(self, inputs, ew):
        for input_name, input_item in inputs.inputs.iteritems():
            state = PersistentState(inputs.metadata, input_name)
            tower_host = input_item['tower_host']
            verify_ssl = False#input_item['verify_ssl']
            username = input_item['username']
            password = input_item['password']
            last_id = state.get('last_id', 0)
            # ew.log(ew.DEBUG, 'last_id = {}'.format(last_id))
            qs = urlparse.urlencode(dict(order_by='id', id__gt=last_id))
            job_events_url = urlparse.urlunsplit(['https', tower_host, '/api/v1/job_events/', qs, ''])
            response = requests.get(job_events_url, auth=(username, password), verify=bool(verify_ssl))
            response.raise_for_status()
            data = response.json()
            for result in data.get('results', []):
                event = Event()
                event.stanza = input_name
                event.data = json.dumps(result)
                ew.write_event(event)
                last_id = max(last_id, result.get('id', 0))
            state['last_id'] = last_id


if __name__ == '__main__':
    import sys
    sys.exit(TowerAppScript().run(sys.argv))
