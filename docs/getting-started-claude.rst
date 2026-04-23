Getting started: Claude Code
============================

This guide assumes you have completed the :ref:`start-codex` section and can
run a Podman container locally as well as on a remote system.

:nih:`NIH-specific` At NIH, setting up Claude Code is more complicated than
Codex because of the hosting mechanism and the login mechanism. Here, we
describe how to host Anthropic models on Amazon Bedrock and authenticate with
AWS SSO. These models are hosted in the `STRIDES <https://cloud.nih.gov>`__
environment. It is possible to use Azure Foundry or Google Vertex AI hosted
models in a similar fashion on STRIDES; that is not yet documented here.

:nih:`NIH-specific` At NIH, you will need an AWS STRIDES account. See `STRIDES
enrollment <https://cloud.nih.gov/enrollment/>`__.


Initial setup
-------------

This first section needs to be done once to make sure accounts are connected
and you can authenticate.


1. :nih:`NIH-specific` Submit a `Cloud Operations Support Request
   <https://myitsm.nih.gov/nih_sd?id=nih_sd_sc_item&sys_id=db4dc8a91b41dc1001e9ea82f54bcb2c>`_
   on ServiceNow to get the relevant accounts added to the AWS Identity Center,
   which enables SSO. This requires a cloud admin. **This only needs to be done
   once per group.** Include:

   - AWS account name and number
   - List of people: names, usernames, and emails
   - Existing security group name to use, or the name of a new security group
     for CIT to create with these users
   - The role to assign users in the security group. We are currently using
     ``NIH-AWS-PowerUser``, one of the standard roles set up in an AWS STRIDES
     account.
2. :nih:`NIH-specific` After answering any follow-up questions from CIT:

   - CIT will either send each user an email directly or cause one to be sent
     through AWS. The email will contain your username, a temporary password,
     and a URL.
   - Visit the URL, log in, change the password, and set up MFA.

   .. tip::

      :nih:`NIH-specific` You are complete with this phase when you can successfully log in to
      https://nih.awsapps.com/start.

3. **Install the AWS Command Line Interface (AWS CLI) Version
   2** (`docs <https://aws.amazon.com/cli/>`_) on your local machine and ensure it is on your ``$PATH``.

   - AWS CLI v2 is used to authenticate with AWS. Claude Code uses it to
     refresh credentials whenever possible, and it is also useful for working
     with API keys.
   - If you already have it installed, make sure you are using version 2. See
     the `v1 to v2 migration docs
     <https://docs.aws.amazon.com/cli/latest/userguide/cliv2-migration.html>`_
     if you need to upgrade.

   .. tip::

      You are complete with this phase when you open a new terminal, activate the
      conda environment if needed, and run :cmd:`aws` to get:

      .. code-block:: text

         aws: [ERROR]: the following arguments are required: command

4. **Run** :cmd:`aws configure sso` and respond as follows.

   The items you need to type or paste are indicated with ``**`` below. Otherwise,
   press Enter to accept defaults. The account number ``00001`` is a placeholder;
   replace it with your actual account number in every command.

   As part of this process, a browser window will open where you need to
   authenticate.

   .. code-block:: text

      ** SSO session name (Recommended): aws-claude
      ** SSO start URL [None]: https://nih.awsapps.com/start
      ** SSO region [None]: us-east-1
         SSO registration scopes [sso:account:access]:
         Attempting to open your default browser.
         If the browser does not open, open the following URL:

         https://oidc.us-east-1.amazonaws.com/authorize?response_type=c.......

         The only AWS account available to you is: 00001
         Using the account ID 00001
         The only role available to you is: AWSPowerUserAccess
         Using the role name "AWSPowerUserAccess"
      ** Default client Region [None]: us-east-1
         CLI default output format (json if not specified) [None]:
         Profile name [AWSPowerUserAccess-00001]:
         To use this profile, specify the profile name using --profile, as shown:

         aws sts get-caller-identity --profile AWSPowerUserAccess-00001

   You can inspect the resulting config in :file:`~/.aws/config`.

5. Run the command it suggests, again using your actual account number:

   .. code-block:: bash

      aws sts get-caller-identity --profile AWSPowerUserAccess-00001

6. We want to use this profile by default, so export these environment
   variables, for example in :file:`~/.bashrc`:

   .. code-block:: bash

      export AWS_PROFILE="AWSPowerUserAccess-00001"
      export AWS_REGION=us-east-1

7. Source your shell config or open a new terminal, then run the same command
   without explicitly specifying the profile:

   .. code-block:: bash

      aws sts get-caller-identity

8. Now run :cmd:`aws sso login`. A browser should open, and if you've just done
   the above steps, you should get a page indicating that you are already
   authenticated.

   .. tip::

      You are complete with this phase when :cmd:`aws sso login` opens the browser
      and you get the confirmation.

.. note::

  To inspect your current credentials, including expiration time, run:

  .. code-block:: bash

     aws configure export-credentials

  If you ever need to refresh credentials manually, run:

  .. code-block:: bash

     aws sso login

  :nih:`NIH-specific` You will likely need to re-run :cmd:`aws sso login` (or use
  the :cmd:`refresh.py` script) every 8 hrs.


Claude Code locally (Podman container)
--------------------------------------

1. On a local Mac, ensure you have Podman Desktop installed and running and
   that you are in a directory you are comfortable giving Claude access to.

2. Run :cmd:`launch.py claude`. This will prompt you to set up the color scheme
   and allow permissions in the directory.

3. Submit a prompt like "testing" to confirm that the model responds.


.. details:: What did this do?

   - :cmd:`launch.py` detected that you're running on a Mac and that Podman is the
     right container runtime
   - If you didn't have any previous Claude Code config, it created
     a :file:`~/.claude.json` file with an empty JSON array (``{}``)
   - The default podman image was downloaded if needed, a container was created
   - The :file:`~/.claude.json` file and any existing :file:`~/.claude` directory was mounted into the container
   - The :file:`~/.aws` diretory was mounted into the container so it could see the AWS credentials.

Claude Code remote (Singularity)
--------------------------------

1. Run the following locally (this example uses the :nih:`NIH-specific` host, biowulf.nih.gov):

   .. code-block:: bash

      refresh.py --remote biowulf.nih.gov

2. Log in to the remote system. If Using NIH's Biowulf, get an interactive node and load the Singularity module:

   .. code-block:: bash

      ssh biowulf.nih.gov      # log in
      sinteractive             # allocate interactive node
      module load singularity  # make Singularity available

3. If you don't already have it available, download the :file:`launch.py` script from the repo to the remote.

4. Run the following:

   .. code-block:: bash

      launch.py claude


.. details:: What did this do?

   - :file:`refresh.py` ran :cmd:`aws sso login` if needed, and then pushed the
     appropriate credentials files (:file:`~/.aws`) to the remote.
   - :file:`launch.py` detected that you're running on Linux so Singularity is the appropriate container runtime
   - The default Singularity image was downloaded
   - Similar to running locally in a Podman container, the appropriate configs
     were mounted into the running Singularity container.


Next steps
----------

Claude Code can be configured to run this automatically whenever authentication
times out, so you should not need to run :cmd:`aws sso login` manually in that
context. See :doc:`claude-config`.
