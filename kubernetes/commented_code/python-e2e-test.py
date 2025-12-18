# explian why we need /usr/bin/env python3
# The shebang line #!/usr/bin/env python3 is used at the very beginning of a script to indicate which interpreter should be used to run the script.

#!/usr/bin/env python3

"""
This script performs end-to-end (E2E) testing of the "study-app" running in a k3d Kubernetes cluster.
High-level flow:
1. (Optionally) create a k3d cluster.
2. Build backend and frontend Docker images.
3. Import those images into the k3d cluster.
4. Deploy Kubernetes manifests via Kustomize.
5. Discover service URLs for frontend and backend (LoadBalancer IPs/ports).
6. Wait for services to become reachable over HTTP.
7. Run backend and frontend tests (API + basic HTML checks).
8. Clean up cluster or namespace depending on flags and test outcome.

"""

import os
import sys
import time
import subprocess
import argparse
import requests
import logging
import shutil
from urllib.parse import urljoin


# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,  # Default log level: INFO and above
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
)
# logger = logging.getLogger("e2e-tests") explian below:
# --> This line creates a logger instance named "e2e-tests".
# A logger is an object that you use to log messages in your application.
# By naming the logger, you can easily identify log messages that come from this specific part of your codebase.
# Using a named logger is beneficial for several reasons:
# 1. Granularity: You can have different loggers for different modules or components of your application.
# This allows you to control logging behavior (like log levels) on a per-module basis
logger = logging.getLogger("e2e-tests")  # Named logger used throughout the script


class K8sTestEnvironment:
    """
    Encapsulates the full lifecycle of the test environment:
    - Cluster creation / deletion (k3d)
    - Docker image build and import
    - Kubernetes deployment (kubectl + kustomize)
    - Service discovery (front/back URLs)
    - Backend & frontend tests
    - Cleanup

    """

    # Is this parameter or argument cluster_name="study-app-cluster", skip_cluster_creation=False
    # --> These are parameters with default values for the __init__ method of the K8sTestEnvironment class.
    # --> What is parameter: A parameter is a variable that is defined in the function or method signature.
    # --> What are arguments: Arguments are the actual values that are passed to the function or method when it is called.

    def __init__(self, cluster_name="study-app-cluster", skip_cluster_creation=False):
        # kip_cluster_creation=False. means we will create and delete the cluster ourselves.
        # If True, we assume the cluster already exists.

        # Name of the k3d cluster to create/use
        self.cluster_name = cluster_name
        # Why use self : Using self allows these variables to be accessed by other methods within the class.
        # if we did not use self, these variables would be local to the __init__ method and not accessible elsewhere.

        # If True, we assume the cluster exists and we do NOT create/delete it
        self.skip_cluster_creation = skip_cluster_creation

        # Directory where this script resides
        # Example: /path/to/project/kubernetes/commented_code
        # Explian why: We use os.path.abspath to get the full path of this script,
        # then os.path.dirname to get its directory.
        # This is useful for locating related files (like k3d-config.yaml)
        # (__file__) gives the path of the current script.
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        # Project root directory (one level up from script)
        self.root_dir = os.path.dirname(self.base_dir)

        # URLs will be populated after deployment and service discovery
        # show where is used: used in test_backend and test_frontend methods to access the backend and frontend services.
        # Why declare here: Declaring these as instance variables allows them to be set once
        # After deployment and then accessed by multiple test methods.
        # What is intance variable: An instance variable is a variable that is associated with a specific instance of a class.
        # Each instance of the class has its own copy of the instance variable.
        # This is in contrast to class variables, which are shared across all instances of the class.
        # Instance variables are typically defined within methods (like __init__) using the self keyword.
        # calss variable vs instance variable:
        # Class variables are shared across all instances of a class, while instance variables are unique to each instance.
        self.backend_url = ""
        self.frontend_url = ""

        # Sample payload used when testing backend "session" endpoints
        # This payload simulates a user session with a duration of 45 minutes and a tag "kubernetes".test_session
        # test_session is a dictionary with two keys:
        # - "minutes": An integer representing the duration of the study session in minutes.
        # - "tag": A string representing a tag or label associated with the study session.
        # where is used this test_session: used in test_backend method when creating a session via POST /sessions endpoint.
        # The backend is expected to echo these values back in the created session response.
        # This allows us to verify that the backend correctly processes and stores session data.
        # Why we need this: This helps ensure that the backend API is functioning correctly.
        # show the code where is used : see test_backend method below.
        # This is also instance variable because it is defined with self.
        self.test_session = {"minutes": 45, "tag": "kubernetes"}

        # Fail fast if kubectl is not installed
        # Why self: Using self allows the method to be called on the instance of the class.
        self.check_kubectl_installed()

    # -------------------------------------------------------------------------
    # Infrastructure / environment utilities
    # -------------------------------------------------------------------------
    # Why we need(self) here: The self parameter is used in instance methods to refer to the instance of the class itself.
    def check_kubectl_installed(self):
        """Ensure that 'kubectl' is installed and available in PATH."""
        # shutil.which("kubectl") shutil is a utility that checks if the given command is available in the system's PATH.
        # -->Is None means that if kubectl is not found, the function will return None.
        # --> What is None: None is a special constant in Python that represents the absence of a value or a null value.
        # None=null in java.
        # is empty and none are same: No, they are not the same.
        # --> None represents the absence of a value, while an empty value (like an empty string, list, or dictionary) is still a defined value, just without any content.
        if shutil.which("kubectl") is None:
            # kubectl not found; without it we cannot manage the cluster or resources
            logger.error(
                "kubectl is not installed or not in PATH. Please install kubectl before running tests."
            )
            sys.exit(1)  # Exit immediately with error code
        logger.info("kubectl is installed and available.")

    # wrapper function to run shell commands from within python commands
    def run_command(self, cmd, cwd=None, shell=False, check=True, capture_output=False):
        # run_command(self, cmd, cwd=None, shell=False, check=True, capture_output=False): what are required and optinonal parameters
        # This method executes a shell command with logging and standardized options.
        # Parameters:
        # - cmd: The command string to execute. Is this requited or optional parameter: Required parameter
        # - cwd: The working directory in which to run the command. Is this requited or optional parameter: Optional parameter (default is None)

        # How to know if parameter is optional or required: If a parameter has a default value (like None),
        # it is optional. If it does not have a default value, it is required.
        # check=True is an optional parameter with a default value of True.

        # check=True what it does mean: If check is True, the method will raise a CalledProcessError if the command exits with a non-zero status (indicating an error).
        # If check is False, the method will not raise an exception on non-zero exit status.

        # how to know: If a parameter has a default value (like True), it is optional. If it does not have a default value, it is required.
        # capture_output=False what is mean if false or true:
        # If capture_output is True, the method captures the standard output and standard error of the command and returns them in the CompletedProcess object.
        # If capture_output is False, the command's output is not captured, and it will be printed directly to the console. What is mean by directly to console:
        # This means that the output of the command will be displayed in the terminal or command prompt where the script is running, rather than being captured and stored for later use.

        # shell=False how to check if shell is True or False: and where is shell come from:
        # The shell parameter determines whether to run the command through the shell (like bash) or directly.
        # If shell is True, the command is executed through the shell, allowing for shell features like pipes and redirection.
        # If shell is False, the command is executed directly without shell features, and we need to provide the command as a list of arguments.

        """
        Run a shell command with logging and standardized options.

        :param cmd: Command string to execute.
        :param cwd: Working directory in which to run the command.
        :param shell: If True, run via shell, otherwise split into args.
        :param check: If True, raise CalledProcessError on non-zero exit status.
        :param capture_output: If True, capture stdout/stderr and return them.
        :return: subprocess.CompletedProcess instance.
        """
        # {cmd} why not have self: cmd is a parameter passed to the method, so we refer to it directly as cmd.
        # If it were an instance variable, we would use self.cmd.
        logger.info(f"Running command: {cmd}")

        # Use shell=True if the command string relies on shell features
        # shell means the command is run through the shell (like bash),
        # allowing for shell features like pipes, redirection, etc.
        # If False, we split the command into a list of arguments.

        # For complex commands, we need shell=True.
        # For simple commands without shell features, we can use shell=False.

        # Explian below:
        # If shell is True, we pass the command string directly to subprocess.run.
        # If shell is False, we split the command string into a list of arguments using cmd.split().

        # What is subproceass run: subprocess.run is a function that runs a command in a subprocess,
        # subprocess is a module for spawning new processes, connecting to their input/output/error pipes,
        # and obtaining their return codes.

        # pass the command string directly to subprocess.run. vs shell is False, we split the command string into a list of arguments using cmd.split().
        # # means that we break the command string into individual components based on spaces. why: This is necessary because subprocess.run expects a list of arguments when shell is False.
        # For example, the command "kubectl get pods" would be split into ["kubectl", "get", "pods"].
        # This allows subprocess.run to execute the command correctly without relying on shell features.
        # In summary, shell=True allows for shell features, while shell=False requires splitting the command into a list of arguments.

        # Dont understand the below: Example:
        # If cmd is "kubectl get pods" and shell is False, we call subprocess.run(["kubectl", "get", "pods"], ...).
        # If shell is True, we call subprocess.run("kubectl get pods", shell=True, ...).
        # what is mean if shell is True or False:
        # If shell is True, the command is executed through the shell, allowing for shell features like pipes and redirection.
        # If shell is False, the command is executed directly without shell features, and we need to provide the command as a list of arguments.
        # This distinction is important for security and functionality, depending on the command being run.
        # If shell is True, we call subprocess.run("kubectl get pods", shell=True, ...).
        # what is  subprocess. run: subprocess.run is a function that runs a command in a subprocess,
        # subprocess is a module for spawning new processes, connecting to their input/output/error pipes,
        # and obtaining their return codes.

        # why we need below if else: We need the if-else structure to handle the two different ways of executing commands
        # where cmd, shell, check, cwd, capture_output come from: These are parameters passed to the run_command method.
        # if we remoove below code what will happen: If we remove the if-else structure,
        # we would not be able to handle commands that require shell features correctly.
        # This could lead to errors when executing commands that rely on shell functionality.
        # For example, commands with pipes or redirection would fail if shell is False.
        # Therefore, the if-else structure is necessary to ensure that commands are executed correctly based on the shell parameter.
        # where run come from: run is a function within the subprocess module.

        # __subprocess defination__
        # “From Python, run this shell command, send it input, capture its output, and check if it succeeded.”
        # result will have object with a .returncode
        # If check is True and the command exits with a non-zero status (which usually means “error”),
        # Python will raise a subprocess.CalledProcessError.
        # capture_output=True The child process’s stdout and stderr are captured into memory instead of being printed to the terminal.
        # After it finishes, you can access:
        # result.stdout → what the command printed to standard output
        # result.stderr → what the command printed to standard error
        # If you dont pass the The command’s output goes straight to the terminal, like if you ran it manually in the shell.
        # result.stdout and result.stderr will be None.
        if shell:
            result = subprocess.run(
                cmd,
                shell=True,
                check=check,
                cwd=cwd,
                capture_output=capture_output,
            )
        else:
            # For simple commands, split on spaces into argument list
            result = subprocess.run(
                cmd.split(),
                check=check,
                cwd=cwd,
                capture_output=capture_output,
            )
        # What will be the result: The result will be a subprocess.CompletedProcess instance,
        # what will be true or false: The result itself is not a boolean value.
        # what will the the value of return result. example: The return value will be a subprocess.CompletedProcess object,
        # --> Default return of function is None in python.

        # result = subprocess.run(...) will be a subprocess.CompletedProcess object.
        # It’s a small object that summarizes what happened when the command ran.
        return result

    def setup_cluster(self):
        """
        Set up a k3d cluster if necessary.

        - If skip_cluster_creation is True, do nothing.
        - Otherwise:
          * Check if the cluster already exists; if so, delete it.
          * Create a new cluster using k3d-config.yaml.
          * Configure kubectl context.
          * Wait until nodes are Ready.
        """
        if self.skip_cluster_creation:
            logger.info("Skipping cluster creation as requested")
            # return nothing means: This means that the function will exit at this point and not execute any further code within it.
            # is method return or if else: This is a return statement that exits the method early.
            # you can retrun in funcion any time you want: Yes, you can use a return statement at any point in a function or method to exit early.
            # --> Why we need return here: In this context, the return statement is used to exit the setup_cluster method early if the skip_cluster_creation flag is set to True.
            return

        # ---------------------------------------------------------------------
        # Check if cluster already exists
        # ---------------------------------------------------------------------
        # self.run_command why self: Using self allows us to call the run_command method on the current instance of the K8sTestEnvironment class.
        result = self.run_command(
            "k3d cluster list",
            shell=True,  # `k3d cluster list` is a simple shell command
            # check=False means: This means that if the command exits with a non-zero status (indicating an error),
            # --> which command fails: In this context, it refers to the "k3d cluster list" command.
            # what is mean if check is False: If check is set to False, the run_command method will not raise an exception if the command fails (i.e., exits with a non-zero status).
            check=False,  # Do not raise if this fails
            capture_output=True,  # --> We want to read stdout of which command : "k3d cluster list"
        )

        # cluster_exists why not self: cluster_exists is a local variable defined within the setup_cluster method.
        #  cluster_exists = False - what it means false means here exist or not exits:
        cluster_exists = False
        # hasattr checks if the result object has the attribute "stdout"
        # This is important because if the command failed and didn't produce any output,
        # trying to access result.stdout directly could raise an AttributeError.
        # is not None means is not empty: This check ensures that the stdout attribute is not None,
        # meaning that there is some output to process.
        if hasattr(result, "stdout") and result.stdout is not None:
            # Decode bytes -> string, then check if our cluster name appears
            # decode("utf-8") why use here and what it means explain:
            # The stdout attribute of the result object is typically in bytes format.
            # --> To convert it to a human-readable string, we use the decode("utf-8") method.
            cluster_exists = self.cluster_name in result.stdout.decode("utf-8")

        # If it exists, delete it to start from a clean state
        if cluster_exists:
            logger.info(f"Cluster {self.cluster_name} exists, deleting it")
            self.run_command(f"k3d cluster delete {self.cluster_name}")

        # ---------------------------------------------------------------------
        # Create new k3d cluster using config file
        # ---------------------------------------------------------------------
        # os.path.join why use os.path.join:
        # os.path.join is used to construct a file path that is compatible with the operating system.
        # It ensures that the correct path separators are used (e.g., "/" for Unix-like systems and "\" for Windows).
        # --> This is important for cross-platform compatibility.
        config_path = os.path.join(self.base_dir, "k3d-config.yaml")
        self.run_command(f"k3d cluster create --config {config_path}")

        # ---------------------------------------------------------------------
        # Point kubectl context at our new cluster
        # ---------------------------------------------------------------------
        # NOTE: This context name must match what k3d created in k3d-config.yaml.
        self.run_command("kubectl config use-context k3d-study-app-cluster")

        # ---------------------------------------------------------------------
        # Wait for nodes to become Ready
        # ---------------------------------------------------------------------
        logger.info("Waiting for cluster to be ready...")
        self.run_command("kubectl wait --for=condition=Ready nodes --all --timeout=60s")

    def build_and_load_images(self):
        """
        Build Docker images for backend and frontend, then import them into the k3d cluster.

        Steps:
        - Build backend: backend:dev
        - Build frontend: frontend:dev
        - Import both into the k3d cluster
        """
        # ------------------------------ Backend --------------------------------
        logger.info("Building backend Docker image")
        self.run_command(
            "docker build -t backend:dev -f ./src/backend/Dockerfile ./src/backend",
            cwd=self.root_dir,  # Run from project root so paths make sense
        )

        # ------------------------------ Frontend -------------------------------
        logger.info("Building frontend Docker image")
        self.run_command(
            "docker build -t frontend:dev -f ./src/frontend/Dockerfile ./src/frontend",
            cwd=self.root_dir,  # Run from project root so paths make sense
        )

        # ---------------------------- Import into k3d -------------------------
        logger.info("Importing images into k3d")
        # Import backend image into cluster
        # from run_command come from above
        self.run_command(f"k3d image import backend:dev -c {self.cluster_name}")
        # Import frontend image into cluster
        self.run_command(f"k3d image import frontend:dev -c {self.cluster_name}")

    def get_service_urls(self):
        """
        Discover external URLs for the frontend and backend services.

        Logic:
        - List services in the `study-app` namespace.
        - Identify services containing "frontend" and "backend" in their names.
        - Poll for LoadBalancer external IPs and ports.
        - Construct http://<ip>:<port> URLs.
        """
        logger.info("Getting LoadBalancer service URLs")

        # Get service names (outputs like "service/frontend-svc", "service/backend-svc")
        result = self.run_command(
            "kubectl get svc -n study-app -o name",
            shell=True,
            check=False,
            capture_output=True,
        )

        # result.returncode != 0:
        # The returncode attribute of the result object indicates the exit status of the command that was run.
        # whuch command: In this context, it refers to the "kubectl get svc -n study-app -o name" command.
        # returncode != 0: where come from. The returncode is set by the subprocess.run function when it executes a command.
        if result.returncode != 0:
            # If kubectl call fails, we can't find services
            logger.error("Failed to get services from namespace")
            # return False will do and will exit the function: This means that the function will exit at this point and return the value False to the caller.
            # and will not execute any further code within it.
            return False

        # Split output into lines, each line is a service name
        # .strip().split("\n") why use strip and split:
        # .strip() is used to remove any leading or trailing whitespace (including newlines) from the output string.
        # .split("\n") is then used to split the cleaned string into a list of lines,
        # using the newline character as the delimiter.
        # EXAMPLE
        # text = "  hello\nworld\n\n  "
        # Two spaces before hello
        # A newline (\n) between hello and world
        # .strip() — cleans the edges only
        # cleaned = text.strip()
        # "hello\nworld"
        # split("\n") — cuts into pieces at newline characters
        # cleaned = "hello\nworld"
        # lines = cleaned.split("\n")
        # ["hello", "world"]
        services = result.stdout.decode("utf-8").strip().split("\n")

        # Will hold the actual service names (no "service/" prefix)
        frontend_svc_name = None
        backend_svc_name = None

        # ---------------------------------------------------------------------
        # Detect services by name pattern
        # ---------------------------------------------------------------------
        for svc in services:
            # Convert "service/frontend-svc" -> "frontend-svc"
            # svc_name = svc.split("/")[-1] explain below:
            # The split("/") method splits the string svc into a list of substrings using "/" as the delimiter.
            # The [-1] index retrieves the last element from that list,
            # which corresponds to the actual service name without the "service/" prefix.
            # For example, if svc is "service/frontend-svc", svc.split("/") results in ["service", "frontend-svc"],
            svc_name = svc.split("/")[-1]
            if "frontend" in svc_name:
                frontend_svc_name = svc_name
                logger.info(f"Detected frontend service: {frontend_svc_name}")
            elif "backend" in svc_name:
                backend_svc_name = svc_name
                logger.info(f"Detected backend service: {backend_svc_name}")

        # not frontend_svc_name or not backend_svc_name what is mean:
        # This condition checks if either frontend_svc_name or backend_svc_name is None or an empty string.
        # --> If either variable is not set (meaning the corresponding service was not found),  the condition evaluates to True.
        # Why we need this check: This check is important to ensure that both the frontend and backend services were successfully identified.
        if not frontend_svc_name or not backend_svc_name:
            logger.error("Could not find frontend and backend services")
            return False

        # ---------------------------------------------------------------------
        # Poll for external IP and port for each service
        # ---------------------------------------------------------------------
        max_retries = 30  # Maximum attempts to wait for external IPs
        for attempt in range(max_retries):
            # ---- Frontend external IP ----
            result = self.run_command(
                f"kubectl get svc -n study-app {frontend_svc_name} "
                "-o jsonpath='{.status.loadBalancer.ingress[0].ip}'",
                shell=True,
                check=False,
                capture_output=True,
            )
            # how go get the ip from the below command:
            # The command kubectl get svc -n study-app {frontend_svc_name} -o jsonpath='{.status.loadBalancer.ingress[0].ip}' retrieves the external IP address of the LoadBalancer service for the frontend.
            frontend_ip = (
                result.stdout.decode("utf-8").strip()
                # This Comes form above command that getting the ip address.
                # if result.returncode == 0 then what is after the if: If the command succeeded (return code 0), we extract the IP address.
                if result.returncode == 0
                # else None means: If the command failed (non-zero return code), we set frontend_ip to None.
                else None
            )

            # ---- Backend external IP ----
            result = self.run_command(
                f"kubectl get svc -n study-app {backend_svc_name} "
                "-o jsonpath='{.status.loadBalancer.ingress[0].ip}'",
                shell=True,
                check=False,
                capture_output=True,
            )
            backend_ip = (
                result.stdout.decode("utf-8").strip()
                if result.returncode == 0
                else None
            )

            # ---- Frontend port ----
            result = self.run_command(
                f"kubectl get svc -n study-app {frontend_svc_name} "
                "-o jsonpath='{.spec.ports[0].port}'",
                shell=True,
                check=False,
                capture_output=True,
            )
            # If port can't be fetched, fall back to a default (cluster-specific)
            frontend_port = (
                result.stdout.decode("utf-8").strip()
                if result.returncode == 0
                # else "22111" means: If the command failed (non-zero return code), we set frontend_port to "22111".
                else "22111"
            )

            # ---- Backend port ----
            result = self.run_command(
                f"kubectl get svc -n study-app {backend_svc_name} "
                "-o jsonpath='{.spec.ports[0].port}'",
                shell=True,
                check=False,
                capture_output=True,
            )
            backend_port = (
                result.stdout.decode("utf-8").strip()
                if result.returncode == 0
                else "21112"
            )

            # If both IPs are available, we can construct our URLs and stop polling
            if frontend_ip and backend_ip:
                self.frontend_url = f"http://{frontend_ip}:{frontend_port}"
                self.backend_url = f"http://{backend_ip}:{backend_port}"
                logger.info(
                    f"Service URLs: Frontend={self.frontend_url}, Backend={self.backend_url}"
                )
                return True

            # If not yet ready, wait and retry
            logger.info(
                f"Waiting for LoadBalancer services to get external IPs... "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(5)

        logger.error("Failed to get service URLs after multiple retries")
        return False

    def deploy_application(self):
        """
        Deploy the application using kubectl + kustomize, then wait for pods & discover URLs.

        Steps:
        - `kubectl apply -k manifests/dev`
        - Wait until all pods in `study-app` namespace are Ready.
        - Call get_service_urls() to initiate URL discovery.
        """
        logger.info("Deploying application using kustomize")

        # Directory containing kustomization.yaml and manifests for 'dev' environment
        kustomize_path = os.path.join(self.base_dir, "manifests/dev")

        # Apply manifests using Kustomize support in kubectl
        self.run_command(f"kubectl apply -k {kustomize_path}")

        # Wait until all pods in the namespace are Ready (or timeout)
        logger.info("Waiting for pods to be ready...")
        self.run_command(
            "kubectl wait --for=condition=Ready pods --all -n study-app --timeout=120s"
        )

        # Discover frontend and backend URLs
        if not self.get_service_urls():
            logger.error("Failed to get service URLs")
            return False

        return True

        # where url valvue come from and from where it passed:
        # The url parameter is passed to the wait_for_service_availability method when it is called.
        # where it used : used in the main test flow after deployment to wait for the backend and frontend services to become reachable.

    def wait_for_service_availability(self, url, max_retries=20, delay=5):
        """
        Poll the given URL until the service responds (HTTP < 500) or we run out of retries.

        :param url: URL to probe (e.g., backend /health endpoint).
        :param max_retries: Number of attempts before giving up.
        :param delay: Delay (in seconds) between attempts.
        :return: True if the service became reachable, False otherwise.
        """
        logger.info(f"Checking service availability: {url}")

        for i in range(max_retries):
            try:
                # Use a short timeout so we don't hang indefinitely on a dead service
                response = requests.get(url, timeout=5)

                # Any status < 500 means the app is reachable (even 4xx is "up")
                if response.status_code < 500:
                    logger.info(f"Service at {url} is available")
                    return True
            except requests.RequestException:
                # Could be connection error, timeout, etc. We'll just retry.
                pass

            logger.info(
                f"Service not ready yet, retrying in {delay} seconds "
                f"(attempt {i + 1}/{max_retries})"
            )
            time.sleep(delay)

        logger.error(f"Service at {url} is not available after {max_retries} attempts")
        # Why I need rerutn false if i done have it and remove it then what will happen:
        # If we remove the return False statement, the function would not return any value when the service does not become reachable after the maximum number of retries
        # --> In Python, if a function does not explicitly return a value, it implicitly returns None.
        # This could lead to confusion for the caller of the function, as they would not be able to distinguish between a service that became reachable (True) and one that did not (None).
        return False

    # -------------------------------------------------------------------------
    # Backend tests
    # -------------------------------------------------------------------------

    def test_backend(self):
        """
        Perform a series of functional tests against the backend API.

        Tests:
        - Root endpoint ("/"):
          * status 200
          * JSON message containing "DevOps Study Tracker API"
        - Health endpoint ("/health"):
          * status 200
          * JSON {"status": "healthy"}
        - Session creation (POST /sessions):
          * status 200
          * response echoes minutes/tag and includes id/timestamp
        - Session listing (GET /sessions):
          * status 200
          * returns a list containing our created session
        - Session filtering (GET /sessions?tag=<tag>):
          * all returned sessions have the specified tag
        - Stats (GET /stats):
          * includes keys: total_time, time_by_tag, total_sessions, sessions_by_tag
          * total_sessions > 0 and our tag appears in sessions_by_tag
        """
        logger.info("Testing backend API")

        try:
            # ----------------------- Root endpoint ----------------------------
            response = requests.get(self.backend_url, timeout=5)
            assert response.status_code == 200, (
                f"Backend root endpoint failed with status code {response.status_code}"
            )

            # Expect a JSON body with 'message' field containing specific text
            assert "DevOps Study Tracker API" in response.json().get("message", ""), (
                "Root endpoint doesn't have expected content"
            )
            logger.info("Backend root endpoint test passed")

            # ----------------------- Health endpoint --------------------------
            response = requests.get(urljoin(self.backend_url, "/health"), timeout=5)
            assert response.status_code == 200, (
                f"Backend health check failed with status code {response.status_code}"
            )
            assert response.json().get("status") == "healthy", (
                "Health endpoint doesn't report as healthy"
            )
            logger.info("Backend health check passed")

            # ----------------------- Create a session -------------------------
            response = requests.post(
                urljoin(self.backend_url, "/sessions"),
                json=self.test_session,  # send test payload
                timeout=5,
            )
            assert response.status_code == 200, (
                f"Session creation failed with status code {response.status_code}"
            )

            created_session = response.json()

            # Check that the backend echoed fields correctly
            assert created_session["minutes"] == self.test_session["minutes"], (
                "Created session has incorrect minutes"
            )
            assert created_session["tag"] == self.test_session["tag"], (
                "Created session has incorrect tag"
            )

            # Ensure backend added metadata fields
            assert "id" in created_session, "Created session doesn't have ID field"
            assert "timestamp" in created_session, (
                "Created session doesn't have timestamp field"
            )
            logger.info("Session creation test passed")

            # ----------------------- Retrieve all sessions --------------------
            response = requests.get(urljoin(self.backend_url, "/sessions"), timeout=5)
            assert response.status_code == 200, (
                f"Session retrieval failed with status code {response.status_code}"
            )

            sessions = response.json()
            assert isinstance(sessions, list), "Sessions endpoint didn't return a list"

            # Ensure at least one returned session matches our test tag
            assert any(
                session["tag"] == self.test_session["tag"] for session in sessions
            ), "Created session not found in sessions list"
            logger.info("Session retrieval test passed")

            # ----------------------- Filter by tag ----------------------------
            response = requests.get(
                urljoin(
                    self.backend_url,
                    f"/sessions?tag={self.test_session['tag']}",
                ),
                timeout=5,
            )
            assert response.status_code == 200, (
                f"Filtered sessions retrieval failed with status code {response.status_code}"
            )

            filtered_sessions = response.json()

            # All sessions in the filtered list must have the requested tag
            assert all(
                session["tag"] == self.test_session["tag"]
                for session in filtered_sessions
            ), "Filtered sessions contain incorrect tags"
            logger.info("Filtered sessions test passed")

            # ----------------------- Retrieve statistics ----------------------
            response = requests.get(urljoin(self.backend_url, "/stats"), timeout=5)
            assert response.status_code == 200, (
                f"Stats retrieval failed with status code {response.status_code}"
            )

            stats = response.json()

            # Basic shape of stats object
            assert "total_time" in stats, "Stats doesn't include total_time"
            assert "time_by_tag" in stats, "Stats doesn't include time_by_tag"
            assert "total_sessions" in stats, "Stats doesn't include total_sessions"
            assert "sessions_by_tag" in stats, "Stats doesn't include sessions_by_tag"

            # There should be at least one session recorded
            assert stats["total_sessions"] > 0, (
                "Stats shows no sessions despite adding one"
            )

            # Our test tag should appear in the sessions_by_tag map
            assert self.test_session["tag"] in stats["sessions_by_tag"], (
                "Added tag not found in stats"
            )
            logger.info("Statistics retrieval test passed")

            return True

        except Exception as e:
            # Catch any assertion errors or request issues and log them
            logger.error(f"Backend test failed: {str(e)}")
            return False

    # -------------------------------------------------------------------------
    # Frontend tests
    # -------------------------------------------------------------------------

    def test_frontend(self):
        """
        Perform simple tests against the frontend.

        Tests:
        - Root HTML page:
          * status 200
          * contains "DevOps Study Tracker"
          * contains a label "Tag:"
          * contains the form and inputs for adding a session
        - Frontend health endpoint (/health):
          * status 200 or 503
          * JSON contains 'status' and 'api_connectivity'
        """
        logger.info("Testing frontend")

        try:
            # ----------------------- Basic connectivity -----------------------
            response = requests.get(self.frontend_url, timeout=5)
            assert response.status_code == 200, (
                f"Frontend check failed with status code {response.status_code}"
            )
            logger.info("Frontend connectivity check passed")

            # Full HTML of the page
            content = response.text

            # ----------------------- Basic content checks ---------------------
            # Ensure page has expected title text
            assert "DevOps Study Tracker" in content, (
                "Frontend page doesn't contain expected title"
            )

            # Ensure page has label for tag input
            assert "Tag:" in content, "Frontend page doesn't contain tag input field"
            logger.info("Frontend content check passed")

            # ----------------------- Form structure checks --------------------
            # Verify that the HTML contains the form for adding a session
            assert 'form action="/add_session"' in content, (
                "Frontend page doesn't contain the session form"
            )
            # Verify the minutes numeric input exists
            assert 'input type="number" id="minutes"' in content, (
                "Frontend page doesn't contain minutes input"
            )
            # Verify a submit button is present
            assert 'button type="submit"' in content, (
                "Frontend page doesn't contain submit button"
            )
            logger.info("Frontend form elements check passed")

            # ----------------------- Health endpoint --------------------------
            health_url = urljoin(self.frontend_url, "/health")
            response = requests.get(health_url, timeout=5)

            # Frontend might return 503 if it can't reach backend, so accept both
            assert response.status_code in [200, 503], (
                f"Frontend health check failed with unexpected status code {response.status_code}"
            )

            health_data = response.json()

            # Health payload should contain 'status' and 'api_connectivity'
            assert "status" in health_data, (
                "Frontend health endpoint doesn't include status field"
            )
            assert "api_connectivity" in health_data, (
                "Frontend health endpoint doesn't include api_connectivity field"
            )
            logger.info("Frontend health endpoint check passed")

            # Note: For full E2E testing, we could use Selenium or another
            # browser automation tool to simulate user interactions.

            return True

        except Exception as e:
            logger.error(f"Frontend test failed: {str(e)}")
            return False

    # -------------------------------------------------------------------------
    # E2E workflow (combining backend + frontend tests)
    # -------------------------------------------------------------------------

    def e2e_test_workflow(self):
        """
        Run the end-to-end workflow tests, ensuring both backend and frontend behave correctly.

        Currently:
        - Simply runs test_backend() and test_frontend() and ANDs the results.

        In the future:
        - Could be extended with real browser-based tests that confirm
          the frontend properly talks to the backend.
        """
        logger.info("Running end-to-end integration tests")

        try:
            backend_ok = self.test_backend()
            frontend_ok = self.test_frontend()

            # True only if both passes
            return backend_ok and frontend_ok

        except Exception as e:
            logger.error(f"E2E test workflow failed: {str(e)}")
            return False

    # -------------------------------------------------------------------------
    # Cleanup logic
    # -------------------------------------------------------------------------

    def cleanup(self):
        """
        Clean up cluster or namespace depending on whether we created the cluster.

        - If we created the cluster (skip_cluster_creation == False), delete the whole cluster.
        - If we reused an existing cluster, only delete the `study-app` namespace.
        """
        # If false(not false) = true then execute below code.
        # That means: by default, we do not skip creating the cluster → the code is expected to create a k3d cluster.
        # The if not self.skip_cluster_creation line. This condition is True when self.skip_cluster_creation is False.
        # not self.skip_cluster_creation is not False → True
        if not self.skip_cluster_creation:
            logger.info("Cleaning up: deleting k3d cluster")
            # Don't raise on failure during cleanup
            self.run_command(f"k3d cluster delete {self.cluster_name}", check=False)
        else:
            logger.info("Cleaning up: removing study-app namespace")
            self.run_command("kubectl delete namespace study-app", check=False)

    # -------------------------------------------------------------------------
    # Orchestrator for the whole run
    # -------------------------------------------------------------------------

    def run(self, cleanup_on_success=True, cleanup_on_failure=False):
        """
        Run the full test suite and optionally clean up resources.

        Steps:
        1. Setup cluster (unless skip_cluster_creation is True).
        2. Build and import Docker images.
        3. Deploy the application with kubectl + kustomize.
        4. Wait for backend and frontend to become available.
        5. Run E2E tests (backend + frontend).
        6. Cleanup based on flags and test success.

        :param cleanup_on_success: If True, cleanup after successful tests.
        :param cleanup_on_failure: If True, cleanup even if tests fail.
        :return: True if tests succeeded, False otherwise.
        """
        success = False  # Track overall success

        try:
            # ----------------------- Setup infrastructure ---------------------
            self.setup_cluster()
            self.build_and_load_images()

            # If self.deploy_application() fails then not fail = true then will trigger this.
            if not self.deploy_application():
                # If deployment fails, we can't proceed with tests
                logger.error("Failed to deploy application")
                return False

            # ----------------------- Wait for availability --------------------
            backend_available = self.wait_for_service_availability(
                urljoin(self.backend_url, "/health")
            )
            frontend_available = self.wait_for_service_availability(self.frontend_url)

            if not backend_available or not frontend_available:
                logger.error("Services did not become available in time")
                return False

            # ----------------------- Run E2E tests ----------------------------
            success = self.e2e_test_workflow()
            logger.info(f"Tests completed with {'SUCCESS' if success else 'FAILURE'}")

            return success

        except Exception as e:
            logger.error(f"Test run failed with exception: {str(e)}")
            return False

        finally:
            # ----------------------- Conditional cleanup ----------------------
            # Only clean up if:
            # - Tests succeeded AND cleanup_on_success is True
            # OR
            # - Tests failed AND cleanup_on_failure is True - cleanup_on_failure=True
            if (success and cleanup_on_success) or (not success and cleanup_on_failure):
                self.cleanup()


# -----------------------------------------------------------------------------
# CLI entrypoint
# ---> python script.py --help
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Setup CLI argument parser with helpful description
    # argparse.ArgumentParser is a helper from the argparse module that lets you define command-line arguments.
    # description= is just text that will show up if someone runs:
    parser = argparse.ArgumentParser(
        description="Run end-to-end tests for study-app in k3d"
    )

    # Flag: skip cluster creation/deletion
    # This defines a command-line argument called skip-cluster-creation.
    # It’s optional (because it starts with --).
    # If the user doesn’t provide it, it defaults to "study-app-cluster".
    # help= is what shows in --help output.
    # skip-cluster-creation - coming from where: This is the name of the command-line argument being defined.
    # coming from init method: This argument corresponds to the skip_cluster_creation parameter in the __init__ method of the K8sTestEnvironment class.
    # python script.py --skip-cluster-creation
    # If the user runs the script with this flag, args.skip_cluster_creation will be set to True.
    # If they omit it, args.skip_cluster_creation will be False.
    #  action="store_true" -  If the user includes the flag → the value becomes True
    # If the user does NOT include the flag → the value becomes False
    # So args.skip_cluster_creation will always be a boolean (True or False).
    # Examples:
    # python script.py. → args.skip_cluster_creation is False (we will create the cluster).
    # python script.py --skip-cluster-creation. args.skip_cluster_creation is True (we will NOT create a new cluster; we’ll use an existing one).

    parser.add_argument(
        "--skip-cluster-creation",
        action="store_true",
        # if you pass --skip-cluster-creation → args.skip_cluster_creation == True. If you don’t pass it → args.skip_cluster_creation == False
        # we can have -> default="study-app-cluster",
        # what is help mean here: This text explains to the user what the flag does when they run the script with --help.
        help="Skip creating a new cluster (use an existing one instead)",
    )

    # Flag: don't cleanup on success (leave resources for debugging)
    # This defines a boolean flag.
    # action="store_true" means:
    # If you include --skip-cluster-creation on the command line → args.skip_cluster_creation will be True.
    # This is the name of the flag the user can pass when running the script.
    # python script.py --no-cleanup
    # If --no-cleanup is present on the command line → set args.no_cleanup = True
    # If --no-cleanup is NOT present → args.no_cleanup = False

    parser.add_argument(
        "--no-cleanup",
        # from where action="store_true" come from: This is a standard way in argparse to define a flag that, when present, sets the corresponding variable to True.
        # what is check_true mean: It means that if the user includes the --no-cleanup flag when running the script, the args.no_cleanup variable will be set to True.
        action="store_true",
        help="Don't cleanup resources after tests (useful for debugging)",
    )

    # Parse command-line arguments
    # This reads the actual command-line arguments the user passed in and puts them into an object called args.
    # After this line you can use:
    # args.skip_cluster_creation
    # args = parser.parse_args() is the line where your script actually reads and processes the command-line arguments.
    # Read all the options the user passed in and store them in args so I can use them in my code.”
    args = parser.parse_args()

    # Initialize test environment based on CLI arguments
    # Here you create an instance of your class K8sTestEnvironment.
    # You pass it the values from the command line:
    # cluster_name will be whatever the user passed as --cluster-name (or "study-app-cluster" by default).
    # skip_cluster_creation will be True or False based on whether the flag was present.
    # Inside __init__ of K8sTestEnvironment, it will run setup code (like checking kubectl).
    # If the user ran with --skip-cluster-creation, then args.skip_cluster_creation is True, so the environment will not try to create a new cluster.
    test_env = K8sTestEnvironment(skip_cluster_creation=args.skip_cluster_creation)

    # For now we’re just verifying that initialization works
    logger.info(
        "Environment initialized. skip_cluster_creation=%s, no-cleanup=%s",
        test_env.skip_cluster_creation,
        # test_env.no-cleanup,
    )

    logger.info("Starting K8sTestEnvironment with args: %s", args)

    # Run tests:
    # - If --no-cleanup is NOT provided -> cleanup_on_success=True
    # - cleanup_on_failure remains False (keep resources on failure for debugging)
    # where run come from : run is a method defined in the K8sTestEnvironment class.
    # You call it on the test_env instance you just created.
    # If user does not pass --no-cleanup:args.no_cleanup == False. not args.no_cleanup == True
    success = test_env.run(cleanup_on_success=not args.no_cleanup)

    # Exit code 0 = success, 1 = failure (important for CI/CD pipelines)
    sys.exit(0 if success else 1)
