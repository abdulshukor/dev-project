#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import shutil


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Abdul-e2e-test")
logger.info("Testing")


class K8sTestEnvironment:
    def __init__(self, cluster_name="study-app-cluster", skip_cluster_creation=False):
        self.cluster_name = cluster_name
        self.skip_cluster_creation = skip_cluster_creation

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.root_dir = os.path.dirname(self.base_dir)

        self.backend_url = ""
        self.frontend_url = ""

        # Sample data for testing
        self.test_session = {"minutes": 45, "tag": "kubernetes"}

        # Check if kubectl is installed
        self.check_kubectl_installed()

    def check_kubectl_installed(self):
        if shutil.which("kubectl") is None:
            logger.error("kubectl is not installed")
            sys.exit(1)
        logger.info("kubectl is installed")


def main():
    parser = argparse.ArgumentParser(
        description="E2E test environment bootstrap for Kubernetes"
    )
    parser.add_argument(
        "--cluster-name",
        default="study-app-cluster",
        help="Name of the Kubernetes cluster to target",
    )
    parser.add_argument(
        "--skip-cluster-creation",
        action="store_true",
        help="If set, do not attempt to create the cluster (only validate environment).",
    )

    args = parser.parse_args()

    logger.info("Starting K8sTestEnvironment with args: %s", args)

    env = K8sTestEnvironment(
        cluster_name=args.cluster_name,
        skip_cluster_creation=args.skip_cluster_creation,
    )

    # For now we’re just verifying that initialization works
    logger.info(
        "Environment initialized. cluster_name=%s, skip_cluster_creation=%s",
        env.cluster_name,
        env.skip_cluster_creation,
    )

    # You can later add more test steps here, e.g.:
    # env.deploy_backend()
    # env.deploy_frontend()
    # env.run_smoke_tests()


if __name__ == "__main__":
    main()
