"""Tests for node configuration."""

# pylint: disable=abstract-class-instantiated
import json
import logging
import pathlib as pl
import time

import allure
import pytest
from cardano_clusterlib import clusterlib

from cardano_node_tests.cluster_management import cluster_management
from cardano_node_tests.tests import common
from cardano_node_tests.utils import cluster_nodes
from cardano_node_tests.utils import helpers
from cardano_node_tests.utils import locking
from cardano_node_tests.utils import temptools

LOGGER = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def epoch_length_start_cluster() -> pl.Path:
    """Update *epochLength* to 1200."""
    shared_tmp = temptools.get_pytest_shared_tmp()

    # need to lock because this same fixture can run on several workers in parallel
    with locking.FileLockIfXdist(f"{shared_tmp}/startup_files_epoch_1200.lock"):
        destdir = shared_tmp / "startup_files_epoch_1200"
        destdir.mkdir(exist_ok=True)

        # return existing script if it is already generated by other worker
        destdir_ls = list(destdir.glob("start-cluster*"))
        if destdir_ls:
            return destdir_ls[0]

        startup_files = cluster_nodes.get_cluster_type().cluster_scripts.copy_scripts_files(
            destdir=destdir
        )
        with open(startup_files.genesis_spec, encoding="utf-8") as fp_in:
            genesis_spec = json.load(fp_in)

        genesis_spec["epochLength"] = 1_500

        with open(startup_files.genesis_spec, "w", encoding="utf-8") as fp_out:
            json.dump(genesis_spec, fp_out)

        return startup_files.start_script


@pytest.fixture(scope="module")
def slot_length_start_cluster() -> pl.Path:
    """Update *slotLength* to 0.3."""
    shared_tmp = temptools.get_pytest_shared_tmp()

    # need to lock because this same fixture can run on several workers in parallel
    with locking.FileLockIfXdist(f"{shared_tmp}/startup_files_slot_03.lock"):
        destdir = shared_tmp / "startup_files_slot_03"
        destdir.mkdir(exist_ok=True)

        # return existing script if it is already generated by other worker
        destdir_ls = list(destdir.glob("start-cluster*"))
        if destdir_ls:
            return destdir_ls[0]

        startup_files = cluster_nodes.get_cluster_type().cluster_scripts.copy_scripts_files(
            destdir=destdir
        )
        with open(startup_files.genesis_spec, encoding="utf-8") as fp_in:
            genesis_spec = json.load(fp_in)

        genesis_spec["slotLength"] = 0.3

        with open(startup_files.genesis_spec, "w", encoding="utf-8") as fp_out:
            json.dump(genesis_spec, fp_out)

        return startup_files.start_script


@pytest.fixture
def cluster_epoch_length(
    cluster_manager: cluster_management.ClusterManager, epoch_length_start_cluster: pl.Path
) -> clusterlib.ClusterLib:
    return cluster_manager.get(
        lock_resources=[cluster_management.Resources.CLUSTER],
        prio=True,
        cleanup=True,
        start_cmd=str(epoch_length_start_cluster),
    )


@pytest.fixture
def cluster_slot_length(
    cluster_manager: cluster_management.ClusterManager, slot_length_start_cluster: pl.Path
) -> clusterlib.ClusterLib:
    return cluster_manager.get(
        lock_resources=[cluster_management.Resources.CLUSTER],
        prio=True,
        cleanup=True,
        start_cmd=str(slot_length_start_cluster),
    )


def check_epoch_length(cluster_obj: clusterlib.ClusterLib) -> None:
    end_sec = 30
    end_sec_padded = end_sec + 30  # padded to make sure tip got updated

    sleep_time = 0

    tip = cluster_obj.g_query.get_tip()
    # TODO: "slotsToEpochEnd" is not present in cardano-node < 1.35.6
    if tip.get("slotsToEpochEnd") is not None:
        epoch = int(tip["epoch"])
        sleep_time = int(tip["slotsToEpochEnd"]) * cluster_obj.slot_length - end_sec

    if sleep_time <= 5:
        epoch = cluster_obj.wait_for_new_epoch()
        sleep_time = cluster_obj.epoch_length_sec - end_sec

    time.sleep(sleep_time)
    assert epoch == cluster_obj.g_query.get_epoch()

    time.sleep(end_sec_padded)
    assert epoch + 1 == cluster_obj.g_query.get_epoch()


@common.SKIPIF_WRONG_ERA
# It takes long time to setup the cluster instance (when starting from Byron).
# We mark the tests as "long" and set the highest priority, so the setup is done at the
# beginning of the testrun, instead of needing to respin a cluster that is already running.
@common.ORDER5_BYRON
@common.LONG_BYRON
class TestBasic:
    """Basic tests for node configuration."""

    @allure.link(helpers.get_vcs_link())
    def test_epoch_length(self, cluster_epoch_length: clusterlib.ClusterLib):
        """Test the *epochLength* configuration."""
        cluster = cluster_epoch_length
        common.get_test_id(cluster)

        assert cluster.slot_length == 0.2
        assert cluster.epoch_length == 1_500
        check_epoch_length(cluster)

    @allure.link(helpers.get_vcs_link())
    def test_slot_length(self, cluster_slot_length: clusterlib.ClusterLib):
        """Test the *slotLength* configuration."""
        cluster = cluster_slot_length
        common.get_test_id(cluster)

        assert cluster.slot_length == 0.3
        assert cluster.epoch_length == 1_000
        check_epoch_length(cluster)
