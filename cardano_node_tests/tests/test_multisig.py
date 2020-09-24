import logging
from pathlib import Path
from typing import List

import allure
import pytest
from _pytest.tmpdir import TempdirFactory

from cardano_node_tests.utils import clusterlib
from cardano_node_tests.utils import helpers
from cardano_node_tests.utils import parallel_run

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def temp_dir(tmp_path_factory: TempdirFactory):
    """Create a temporary dir and change to it."""
    tmp_path = Path(tmp_path_factory.mktemp(helpers.get_id_for_mktemp(__file__)))
    with helpers.change_cwd(tmp_path):
        yield tmp_path


# use the "temp_dir" fixture for all tests automatically
pytestmark = pytest.mark.usefixtures("temp_dir")


class TestMultisig:
    @pytest.fixture
    def payment_addrs(
        self,
        cluster_manager: parallel_run.ClusterManager,
        cluster: clusterlib.ClusterLib,
    ) -> List[clusterlib.AddressRecord]:
        """Create new payment addresses."""
        data_key = id(self.payment_addrs)
        cached_value = cluster_manager.cache.test_data.get(data_key)
        if cached_value:
            return cached_value  # type: ignore

        addrs = helpers.create_payment_addr_records(
            *[f"multi_addr{i}" for i in range(5)], cluster_obj=cluster
        )
        cluster_manager.cache.test_data[data_key] = addrs

        # fund source addresses
        helpers.fund_from_faucet(
            addrs[0],
            cluster_obj=cluster,
            faucet_data=cluster_manager.cache.addrs_data["user1"],
        )

        return addrs

    @allure.link(helpers.get_vcs_link())
    def test_multisig_all(
        self, cluster: clusterlib.ClusterLib, payment_addrs: List[clusterlib.AddressRecord]
    ):
        """Send funds to and from script address using the "all" script."""
        temp_template = helpers.get_func_name()

        payment_vkey_files = [p.vkey_file for p in payment_addrs]
        payment_skey_files = [p.skey_file for p in payment_addrs]

        # create multisig script
        multisig_script = cluster.build_multisig_script(
            script_type_arg=clusterlib.MultiSigTypeArgs.ALL,
            payment_vkey_files=payment_vkey_files,
            script_name=temp_template,
        )

        # create script address
        script_addr = cluster.gen_script_addr(multisig_script)

        def _multisig(src_address: str, dst_address: str, amount: int, witness_script=False):
            src_init_balance = cluster.get_address_balance(src_address)
            dst_init_balance = cluster.get_address_balance(dst_address)

            # create TX body
            destinations = [clusterlib.TxOut(address=dst_address, amount=amount)]
            fee = cluster.calculate_tx_fee(
                src_address=src_address,
                tx_name=temp_template,
                txouts=destinations,
                witness_count_add=len(payment_skey_files),
            )
            tx_raw_output = cluster.build_raw_tx(
                src_address=src_address,
                tx_name=temp_template,
                txouts=destinations,
                fee=fee,
            )

            # create witness file for each key
            witness_files = [
                cluster.witness_tx(tx_body_file=tx_raw_output.out_file, signing_key_files=[skey])
                for skey in payment_skey_files
            ]
            if witness_script:
                witness_files.append(
                    cluster.witness_tx(
                        tx_body_file=tx_raw_output.out_file, script_file=multisig_script
                    )
                )

            # sign TX using witness files
            tx_witnessed_file = cluster.sign_witness_tx(
                tx_body_file=tx_raw_output.out_file,
                witness_files=witness_files,
                tx_name=temp_template,
            )

            # submit signed TX
            cluster.submit_tx(tx_witnessed_file)
            cluster.wait_for_new_block(new_blocks=2)

            assert (
                cluster.get_address_balance(src_address)
                == src_init_balance - tx_raw_output.fee - amount
            ), f"Incorrect balance for source address `{src_address}`"

            assert (
                cluster.get_address_balance(dst_address) == dst_init_balance + amount
            ), f"Incorrect balance for script address `{dst_address}`"

        # send funds to script address
        _multisig(src_address=payment_addrs[0].address, dst_address=script_addr, amount=300_000)

        # send funds from script address
        _multisig(
            src_address=script_addr,
            dst_address=payment_addrs[0].address,
            amount=1000,
            witness_script=True,
        )
