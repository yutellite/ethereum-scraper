import scrapy
import json

from ethscraper.mapper.block_mapper import EthBlockMapper
from ethscraper.eth_json_rpc_client import EthJsonRpcClient
from ethscraper.mapper.erc20_transfer_mapper import EthErc20TransferMapper
from ethscraper.mapper.transaction_mapper import EthTransactionMapper
from ethscraper.mapper.transaction_receipt_mapper import EthTransactionReceiptMapper
from ethscraper.service.erc20_processor import EthErc20Processor


class JsonRpcSpider(scrapy.Spider):
    name = "JsonRpcSpider"
    block_mapper = EthBlockMapper()
    transaction_mapper = EthTransactionMapper()
    transaction_receipt_mapper = EthTransactionReceiptMapper()
    erc20_transfer_mapper = EthErc20TransferMapper()
    erc20_processor = EthErc20Processor()

    export_transactions = True
    export_erc20_transfers = True

    def _set_crawler(self, crawler):
        super(JsonRpcSpider, self)._set_crawler(crawler)
        json_rpc_url = self.settings['ETH_JSON_RPC_URL']
        self.eth_client = EthJsonRpcClient(json_rpc_url)

        self.export_transactions = bool(self.settings['EXPORT_TRANSACTIONS'])
        self.export_erc20_transfers = bool(self.settings['EXPORT_ERC20_TRANSFERS'])

    def start_requests(self):
        start_block = int(self.settings['START_BLOCK'])
        end_block = int(self.settings['END_BLOCK'])

        if start_block > end_block:
            self.logger.warning("START_BLOCK {} is greater than END_BLOCK {}").format(start_block, end_block)
            return

        for block_number in range(start_block, end_block + 1):
            request = self.eth_client.eth_getBlockByNumber(block_number)
            request.callback = self.parse_block
            request.errback = self.errback
            yield request

    def parse_block(self, response):
        for err in self.handle_error(response):
            yield err
        json_response = json.loads(response.body_as_unicode())
        result = json_response.get('result', None)
        if result is None:
            return
        block = self.block_mapper.json_dict_to_block(result)

        yield self.block_mapper.block_to_dict(block)

        if self.export_transactions or self.export_erc20_transfers:
            for tx in block.transactions:
                if self.export_transactions:
                    yield self.transaction_mapper.transaction_to_dict(tx)
                if self.export_erc20_transfers:
                    tx_receipt_request = self.eth_client.eth_getTransactionReceipt(tx.hash)
                    tx_receipt_request.callback = self.parse_transaction_receipt
                    tx_receipt_request.errback = self.errback
                    yield tx_receipt_request

    def parse_transaction_receipt(self, response):
        for err in self.handle_error(response):
            yield err
        json_response = json.loads(response.body_as_unicode())
        result = json_response.get('result', None)
        if result is None:
            return
        receipt = self.transaction_receipt_mapper.json_dict_to_transaction_receipt(result)

        erc20_transfers = self.erc20_processor.filter_transfers_from_receipt(receipt)

        for erc20_transfer in erc20_transfers:
            yield self.erc20_transfer_mapper.erc20_transfer_to_dict(erc20_transfer)

    def handle_error(self, response):
        json_response = json.loads(response.body_as_unicode())
        if 'error' in json_response:
            yield {
                'type': 'err',
                'url': response.request.url,
                'code': json_response['error'].get('code', None),
                'message': json_response['error'].get('message', None)
            }

    def errback(self, failure):
        self.logger.error(repr(failure))
