Setting up AWS Single Sign-On
=============================

Why?
----

AWS SSO is required for using Amazon Bedrock models, for example with Claude
Code and Pi. If you are only using Codex, you do not need this.

Setting up AWS SSO allows any tool using the AWS SDK to authenticate as well.
That gives you lots of flexibility to use many parts of AWS, not just limited
to LLM usage.

The "managed profile", ``llm-export``, is a minimal profile with a read-only,
temporary token provided to the running container. This avoids leaking full AWS
credentials inside the container.

It is possible to use Azure or Google Cloud Platform instead of AWS, but that
is not documented here yet.

How it works
------------

Once you set up an SSO profile, :ref:`refresh` will use that to get temporary
credentials from AWS. It will put export those credentials into a JSON file,
which is mounted by :ref:`launch` into a running container. If you use
``refresh.py --remote <hostname>``, then this JSON will get pushed to the
remote as well. Inside a running container, the AWS profile is set to the
special ``llm-export`` profile. That special profile knows that it needs to
read the JSON file with credentials. This happens on every model call.

The reason we do all of this is because:

- a remote machine over ssh can't open a browser for authentication
- token refreshes often can't reach back into the container without exposing
  additional ports
- even if we put the whole AWS config dir in the container, *Pi caches
  credentials at load time*. That means if the auth token expires mid-session,
  the only way to re-auth would be to quit and then restart Pi, which is
  disruptive.

Your SSO profile is the *source* from which :cmd:`refresh.py` obtains
credentials. That's what is set up below in the account provisioning. Once that
is set up, the *managed profile* ``llm-export`` is the *destination* that
:cmd:`refresh.py` writes. This managed profile is only used by ``launch.py``
and ``refresh.py``.

.. list-table:: Where should ``AWS_PROFILE`` be set?
   :header-rows: 1
   :widths: 22 28 50

   * - Where
     - ``AWS_PROFILE``
     - What to do
   * - Local machine (where you log in through a browser)
     - Your SSO source profile, for example
       ``AWSPowerUserAccess-00001``
     - Set it in your shell, **or** leave it unset and pass
       ``refresh.py --aws-profile PROFILE``. Never use ``llm-export`` as the
       source.
   * - Remote host
     - Leave unset
     - Run :cmd:`refresh.py --remote HOST` on the local machine. It copies the
       managed ``llm-export`` destination bundle to the remote host.
   * - Container (local or remote)
     - ``llm-export``, selected automatically by :cmd:`launch.py`
     - Do not set it yourself. Only use ``launch.py --env AWS_PROFILE=...``
       when intentionally overriding the managed profile.

Thus, a typical setup has ``AWS_PROFILE=AWSPowerUserAccess-00001`` on your
laptop, no ``AWS_PROFILE`` on the remote host, and an automatically selected
``AWS_PROFILE=llm-export`` inside the container.

Read on for how to set this up.

1. :nih:`NIH-specific` Account provisioning
-------------------------------------------

.. warning::

   This section is :nih:`NIH-specific`; other institutions will have a different
   process. Once you can successfully authenticate to the SSO start URL for your
   institution, continue to step 2, "AWS CLI v2 setup".

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
  - Either an existing security group name to use, or the name of a new
    security group for CIT to create with these users
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
credentials whenever possible, and it is also useful for working with API keys
if you end up needing that; see :doc:`bedrock-keys` for more on this.

- Install the `AWS Command Line Interface (AWS CLI) Version 2 <https://aws.amazon.com/cli/>`_
  and ensure it is on your ``$PATH``.

  - If you already have it installed, make sure you are using version 2. See
    the `v1 to v2 migration docs <https://docs.aws.amazon.com/cli/latest/userguide/cliv2-migration.html>`_
    if you need to upgrade.

.. tip::

   You are complete with this phase when you open a new terminal, run
   :cmd:`aws` and get:

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

Then run the command it suggests at the end, again using your actual account number:

.. code-block:: bash

   aws sts get-caller-identity --profile AWSPowerUserAccess-00001

We want to use this profile by default, so export these environment variables,
for example in :file:`~/.bashrc`. **This should only be done on the local machine.**

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
   flow successfully and the page says, *"Your credentials have been shared
   successfully and can be used until your session expires. You can now close
   this tab."*

4. Routine usage
----------------

Once AWS SSO is set up, it usually does not need to be changed and you just use
it to refresh credentials.

The typical use-case for this repo is to use :ref:`refresh`, which checks the
local SSO source profile and writes validated, short-lived credentials to the
managed :file:`~/.aws/llm-export` destination profile. The source profile and
``llm-export`` are different: select the source with ``--aws-profile`` or
``AWS_PROFILE``; do not configure ``llm-export`` as an SSO source profile.

If you have more than one profile configured, or you don't want to rely on
``AWS_PROFILE`` being exported, tell :cmd:`refresh.py` which profile to read
credentials from:

.. code-block:: bash

   refresh.py --aws-profile AWSPowerUserAccess-00001

.. note::

   A valid managed bundle takes priority over an inherited host
   ``AWS_PROFILE``. Use ``launch.py --env AWS_PROFILE=...`` to explicitly request
   a different container profile instead of ``llm-export``.

   Remote hosts normally leave ``AWS_PROFILE`` unset because they use the
   managed bundle copied by :cmd:`refresh.py --remote`.

The SSO session lasts for as long as the AWS account admins have configured. It
can be hours or days before you need to log in again. Within that window, the
AWS CLI/SDK on the local host can refresh the shorter-lived (typically 1-hour)
role credentials as needed. The exported ``llm-export`` bundle is a snapshot;
rerun :ref:`refresh` to replace it.

.. warning::

   **This automatic refreshing of the short-lived credentials only works on the
   local machine.** See :ref:`container-notes-login-model` for why.

   This means that if you are working on a remote machine, and the short-lived
   credentials expire every hour, you will need to run :ref:`refresh` with
   ``--remote HOST`` every hour. Only the managed export bundle is copied; the
   local :file:`~/.aws/sso` cache is never transferred.

   To streamline this as much as possible, you may want to ensure that:

   - you have an SSH key set up on the remote host
   - you have the ssh agent running with that key
   - you create an alias like ``alias r='refresh.py --remote biowulf.nih.gov'``
     (or whatever host name you are working on).

   Then it becomes a matter of hitting ``r`` on the local machine once an hour.


At any point, running this on a local machine will open a browser for reauthentication:

.. code-block:: bash

   aws sso login
