import logging
import os


## NOTE: imports of django-related things are done in the methods where they necessary
##       in case of global import 'unittest discover' command fails because Django is not configured yet

class ClientTF:
    """
    Actions with clients intended for Terraform scripts
    """

    def get_client(self, **search_params):
        """
        Return filtered clients list as expected by filters
        Non-existed fields are ignored
        :param search_params: query parameters
        :return dict: list of client data or None
        """
        search_params['is_active'] = search_params.get('is_active', True)
        logging.debug('Requested data for clients with: ' + str(search_params))

        from oc_delivery_apps.dlmanager.models import Client
        try:
            _clients = Client.objects.filter(**search_params).order_by('code')
        except Client.DoesNotExist as _e:
            _clients = list()

        _result = list()
        for _record in _clients:
            _record = _record.__dict__
            _result.append(dict((__k, _record[__k]) for __k in sorted(_record.keys()) if not __k.startswith('_')))

        logging.debug("Returning '%s'" % str(_result))
        return _result

    def put_client(self, **client):
        """
        Put new client from data
        :param client: client data
        """
        logging.debug('Requested to put client with: ' + str(client))

        from oc_delivery_apps.dlmanager.models import Client, FtpUploadClientOptions
        _client, _ = Client.objects.get_or_create(code=client['code'])
        _client.country = client['country']
        _client.language = self.find_language(client.get('language'), client.get('language_id'))
        _client.is_active = client.get('is_active', True)
        _client.save()

        _ftp_options, _ftp_created = FtpUploadClientOptions.objects.get_or_create(client=_client)
        if _ftp_created:
            _ftp_options.save()

        logging.debug('Сlient with code [%s] created successfully' % _client.code)

    def delete_client(self, **client):
        """
        Delete client given by client code
        :param client: client data
        """
        logging.debug('Requested deletion of client with code [%s]' % client['code'])

        from oc_delivery_apps.dlmanager.models import Client
        try:
            _client = Client.objects.get(code=client['code'])
        except Client.DoesNotExist as _e:
            logging.exception(_e)
            return

        logging.debug('Fetched [%s]' % _client)

        _client.is_active = False
        _client.save()

        logging.debug('Сlient with code [%s] deleted successfully' % client['code'])

    def find_language(self, language=None, language_id=None):
        """
        Find a language record and return it
        :param language: language code or name
        :param language_id: language ID
        :return client language
        """
        from oc_delivery_apps.dlmanager.models import ClientLanguage
        if isinstance(language_id, int):
            try:
                return ClientLanguage.objects.get(id=language_id)
            except ClientLanguage.DoesNotExist as _e:
                logging.exception(_e)
                pass

        if all([language, isinstance(language, str)]):
            try:
                return list(ClientLanguage.objects.filter(code__iexact=language)).pop()
            except IndexError as _e:
                logging.exception(_e)
                pass

            try:
                return list(ClientLanguage.objects.filter(description__iexact=language)).pop()
            except IndexError as _e:
                logging.exception(_e)
                pass

        return ClientLanguage.objects.get(code=os.getenv('CLIENT_LANG_DEFAULT', 'en'))
