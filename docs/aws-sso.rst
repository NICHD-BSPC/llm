Setting up AWS STRIDES Single Sign-On
=====================================

Why?
----

AWS SSO is required for using Amazon Bedrock models, for example with Claude
Code. If you are only using Codex, you do not need this.

Setting up AWS SSO allows any tool using the AWS SDK to authenticate as well,
so it affords substantial flexibility.

It is possible to use Azure or Google Cloud Platform instead of AWS, but that
is not documented here yet.


1. :nih:`NIH-specific` Account provisioning
-------------------------------------------

.. warning::

   This section is :nih:`NIH-specific`; other institutions will have a different
   process. Once you can successfully authenticate to the SSO start URL for your
   institution, continue to step 2.

**Prerequisites:**

1. You have an AWS STRIDES account already set up.
2. You have the list of people to include in a security group who will be able
   to log in to AWS.

First, you need to get the relevant accounts added to the AWS Identity Center,
which enables SSO. This is a manual setup on CIT's part since NIH's
integration with EntraID is not yet complete.

This initial setup only needs to be done once per group.

- Submit a `Cloud Operations Support Request <https://myitsm.nih.gov/nih_sd?id=nih_sd_sc_item&sys_id=db4dc8a91b41dc1001e9ea82f54bcb2c>`_
  on ServiceNow. Include:

  - AWS account name and number
  - List of people: names, usernames, and emails
  - Existing security group name to use, or the name of a new security group
    for CIT to create with these users
  - The role to assign users in the security group. We are currently using
    ``NIH-AWS-PowerUser``, one of the standard roles set up in an AWS STRIDES
    account.

- After answering any follow-up questions from CIT:

  - CIT will either send each user an email directly or cause one to be sent
    through AWS. The email will contain your username, a temporary password,
    and a URL.
  - Visit the URL, log in, change the password, and set up MFA.

.. tip::

   You are complete with this phase when you can successfully log in to
   https://nih.awsapps.com/start.

2. AWS CLI v2 setup
-------------------

AWS CLI v2 is used to authenticate with AWS. Claude Code uses it to refresh
credentials whenever possible, and it is also useful for working with API keys;
see :doc:`bedrock-keys`.

- Install the `AWS Command Line Interface (AWS CLI) Version 2 <https://aws.amazon.com/cli/>`_
  and ensure it is on your ``$PATH``.

  - If you already have it installed, make sure you are using version 2. See
    the `v1 to v2 migration docs <https://docs.aws.amazon.com/cli/latest/userguide/cliv2-migration.html>`_
    if you need to upgrade.

.. tip::

   You are complete with this phase when you open a new terminal, activate the
   conda environment if needed, and run :cmd:`aws` to get:

   .. code-block:: text

      aws: [ERROR]: the following arguments are required: command

3. Set up AWS SSO
-----------------

Run :cmd:`aws configure sso` and respond as follows.

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

Then run the command it suggests, again using your actual account number:

.. code-block:: bash

   aws sts get-caller-identity --profile AWSPowerUserAccess-00001

We want to use this profile by default, so export these environment variables,
for example in :file:`~/.bashrc`:

.. code-block:: bash

   export AWS_PROFILE="AWSPowerUserAccess-00001"
   export AWS_REGION=us-east-1

Source your shell config or open a new terminal, then run the same command
without explicitly specifying the profile:

.. code-block:: bash

   aws sts get-caller-identity

To inspect your current credentials, including expiration time, run:

.. code-block:: bash

   aws configure export-credentials

If you ever need to refresh credentials manually, run:

.. code-block:: bash

   aws sso login

This opens a browser. It may immediately report that your credentials have been
shared successfully and can be used until your session expires.

.. tip::

   You are complete with this phase when :cmd:`aws sso login` opens the browser
   flow successfully and you receive the shared-credentials confirmation.

4. Routine usage
----------------

Once AWS SSO is set up, it usually does not need to be touched again.

The SSO session typically lasts about eight hours before you need to log in
again. Within that window, the AWS SDK automatically refreshes the shorter-lived
role credentials as needed.

Running:

.. code-block:: bash

   aws sso login

opens a browser for reauthentication.

**Importantly, this only works on a local machine.** :cmd:`aws sso login` listens on a
port on the machine where it is called. After login, the browser sends a
response back to ``localhost`` on that same machine.

To use these credentials on another host, you can manually transfer them or use
the :doc:`tools` described :cmd:`refresh.py` workflow.
