from datetime import time
import json
import os
import csv
import io
from flask import Response, request
from .client_getter import ClientGetter
from . import client_provider_bp
from .client_counterparty import ClientCounterparty
import logging
from .client_tf import ClientTF

client_getter = ClientGetter()


def response_json(code, data):
    """
    Return JSON data response
    :param int code: HTTP response code
    :param data: dict or list to send as response content
    """
    if not isinstance(data, str):
        data = json.dumps(data)

    # content_type implements a response header 'Content-type: xxxx'
    # mimetype is internal flask parameter not visible to requestor
    # we need a header to be set exactly in many cases, especially for Rundeck
    # see https://flask.palletsprojects.com/en/3.0.x/quickstart/#about-responses
    return Response(
        status=code,
        content_type='application/json',
        mimetype='application/json',
        response=data)


def response_csv(code, data):
    """
    Return CSV-formatted response
    :param int code: HTTP response code
    :param list data: data to be returned
    """
    if not data:
        data = list()

    if not isinstance(data, list):
        data = [data]

    si = io.StringIO(initial_value="", newline='\n')

    if data:
        # first line is supposed to be headers
        # NOTE: do not use '.pop(0)' since it is destructive and first line values
        #       will be omitted then
        headers = data[0].keys()
        dict_writer = csv.DictWriter(si, headers)
        dict_writer.writeheader()
        dict_writer.writerows(data)

    return Response(
        status=code,
        mimetype='text/csv',
        response=si.getvalue())


def _adjust_arguments(args):
    """
    Convert and filter arguments
    Do not raise any exception, just remove invalid
    :param dict args: what to filter
    """
    if not args:
        return args

    for __k in list(args.keys()):
        # non-string arguments is not allowed for this exact service
        __v = args.get(__k)

        if not isinstance(__v, str):
            continue

        __v = __v.strip().replace("\t", " ").replace(" ", "_")

        if not __v:
            del(args[__k])
            continue

        args[__k] = __v

    return args


@client_provider_bp.route('/rundeck/clients', methods=['GET'])
@client_provider_bp.route('/clients', methods=['GET'])
def get_client_list():
    """
    Endpoint returning list of active clients
    The difference between '/rundeck/clients' and general '/clients' endpoints:
    1. Clients are sorted alphabetically
    2. No '404' error for empty list
    """
    logging.info("GET [%s] from [%s]" % (request.url_rule.rule, request.remote_addr))
    try:
        client_list = client_getter.get_clients()
    except Exception as _e:
        logging.exception(_e)
        return response_json(500, {"result": str(_e)})

    if not client_list:
        if 'rundeck' not in request.url_rule.rule:
            return response_json(404, {"result": "Client not found"})

        client_list = list()

    if 'rundeck' in request.url_rule.rule:
        client_list.sort()

    return response_json(200, client_list)

@client_provider_bp.route('/client_lang', methods=['POST'])
def get_client_lang_list():
    """
    Endpoint returning map of client: lang by given list of clients
    """
    logging.info("POST /client_lang from [%s]" % request.remote_addr)
    try:
        client_list = request.json
        client_lang_dict = client_getter.get_client_lang_list(client_list)
    except Exception as _e:
        logging.exception(_e)
        return response_json(500, {"result": str(_e)})

    if not client_lang_dict:
        return response_json(404, {"result": "Client not found"})

    return response_json(200, client_lang_dict)

@client_provider_bp.route('/deliveries', methods=['POST'])
def get_client_deliveries():
    """
    Endpoint returning list of client's deliveries
    """
    logging.info("POST /deliveries from [%s]" % request.remote_addr)
    timezone = request.json.get('timezone') or 'Etc/UTC'
    need_csv = request.json.get('csv', True)

    # workaround about buggy specification which allows 'need_cvs' transmittion as string
    if isinstance(need_csv, str):
        need_csv = bool(need_csv.strip().lower() in ['', 'yes', 'true'])

    client = request.json.get("client")

    if not client:
        return response_json(400, {"result": "Client code must be specified"})

    search_params = request.json.get('search_params') or dict()

    delivery_list, error = client_getter.get_deliveries(client, search_params, timezone)

    if not delivery_list and not error:
        return response_json(404, {"result": "No deliveries found for client %s" % client})

    if error:
        return response_json(500, {"result": error})

    if need_csv:
        return response_csv(201, delivery_list)

    return response_json(201, delivery_list)


@client_provider_bp.route('/v2/deliveries', methods=['POST'])
def get_client_deliveries_v2():
    """
    Endpoint returning list of client's deliveries
    """
    logging.info("POST /v2/deliveries from [%s]" % request.remote_addr)
    timezone = request.json.get('timezone') or 'Etc/UTC'
    client = request.json.get("client")

    if not client:
        return response_json(400, '{"result": "Client code must be specified"}')

    search_params = request.json.get('search_params') or dict()
    delivery_list, error = client_getter.get_deliveries_v2(client, search_params, timezone)

    if not delivery_list and not error:
        return response_json(404, {"result": "No deliveries found for client %s" % client})

    if error:
        return response_json(500, {"result": error})

    return response_json(201, delivery_list)


@client_provider_bp.route('/get_client_data/<int:client_id>', methods=['GET'])
def get_client_data(client_id):
    """
    Endpoint returning client data by id
    """
    logging.info("GET /get_client_data/%i from [%s]" % (client_id, request.remote_addr))
    try:
        client_data = client_getter.get_client_data(client_id)
    except Exception as _e:
        logging.exception(_e)
        return response_json(500, {"result": str(_e)})

    if not client_data:
        return response_json(404, {"result": "Client not found (id=[%d])" % client_id})

    return response_json(200, client_data)

@client_provider_bp.route('/client_counterparty/<string:client_code>', methods=['GET'])
def get_counterparty(client_code):
    """
    Endpoint returning client counterparty
    """
    logging.info("GET /client_counterparty/%s from [%s]" % (client_code, request.remote_addr))
    return response_json(200, {client_code: ClientCounterparty().client_counterparty(client_code)})

@client_provider_bp.route('/sync_customer_tf', methods=['GET', 'PUT', 'DELETE'])
def sync_customer_tf():
    """
    Synchronize client record and return filtered list as requested
    """
    # doing our business depending on request type
    # returning normal JSON response
    logging.info("/sync_customer_tf from [%s]" % request.remote_addr)

    _rq_args = _adjust_arguments(request.args.to_dict())
    logging.debug(f"Args: [{_rq_args}]")

    _client_tf = ClientTF()
    # fork upon method used
    if request.method in ['PUT', 'DELETE']:
        _rq_json = _adjust_arguments(request.json)
        logging.debug(f"JSON: [{_rq_json}]")
        try:
            getattr(_client_tf, f"{request.method.lower()}_client")(**_rq_json)
        except Exception as _e:
            logging.exception(_e)
            return response_json(400, {"result": f"{repr(_e)}"})

    return response_json(201 if request.method == 'PUT' else 200, _client_tf.get_client(**_rq_args))
