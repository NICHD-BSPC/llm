Getting started: Claude Code
============================

This guide assumes you have already completed the :doc:`getting-started-codex`
section and can run Codex in a Podman container locally as well as on a remote
system.

:nih:`NIH-specific` At NIH, setting up Claude Code is more complicated than
Codex because of the hosting mechanism and the login mechanism. Here, we
describe how to host Anthropic models on Amazon Bedrock and authenticate with
AWS SSO. These models are hosted in the `STRIDES <https://cloud.nih.gov>`__
environment. It is possible to use Azure Foundry or Google Vertex AI hosted
models in a similar fashion on STRIDES; that is not yet documented here.

:nih:`NIH-specific` At NIH, you will need an AWS STRIDES account. See `STRIDES
enrollment <https://cloud.nih.gov/enrollment/>`__.


Step 1. Initial AWS SSO setup
-----------------------------

This first section needs to be done once to make sure accounts are connected
and you can authenticate.

1. **Set up AWS SSO.**  See :nih:`NIH-specific` :doc:`aws-sso` for the full
   walkthrough. This includes setting up your group for access, installing AWS
   CLI v2, and authenticating. You should be able to successfully log in with
   :cmd:`aws sso login`.

Step 2. Export env vars
-----------------------

Export these environment variables, for example in :file:`~/.bashrc`:

   .. code-block:: bash

      # Env vars that will be passed to Claude Code
      export CLAUDE_CODE_USE_BEDROCK=1                  # Tells Claude to expect Bedrock
      export CLAUDE_CODE_NO_FLICKER=1                   # Improves interface
      export CLAUDE_CODE_DISABLE_AUTOUPDATER=1          # Don't autoupdate
      export CLAUDE_CODE_DISABLE_INSTALLATION_CHECKS=1  # Don't check installation

      # Env vars to configure which Amazon Bedrock models to use.
      #
      # Otherwise we get the message: "Sonnet: Sonnet 4.5 not available — using
      # Sonnet 4 for this session; Haiku: Haiku 4.5 not available — using Claude
      # 3.5 Haiku for this session."
      #
      # In v2.1.119, it seems OK to not set the Opus default model; selecting
      # it with the /model command sets it to the value we use below.

      export ANTHROPIC_DEFAULT_OPUS_MODEL="us.anthropic.claude-opus-4-6-v1"
      export ANTHROPIC_DEFAULT_SONNET_MODEL="us.anthropic.claude-sonnet-4-6"
      export ANTHROPIC_DEFAULT_HAIKU_MODEL="us.anthropic.claude-haiku-4-5-20251001-v1:0"

      # These should have been exported already during the previous step
      export AWS_PROFILE="AWSPowerUserAccess-00001"  # use your own account here
      export AWS_REGION=us-east-1

.. tip::

  You are complete with this phase when :cmd:`aws sso login` opens the browser
  and you get the confirmation, and running :cmd:`echo
  $CLAUDE_CODE_USE_BEDROCK` gives ``1``.


.. note::

   Although the `Claude Code on Amazon Bedrock
   <https://code.claude.com/docs/en/amazon-bedrock>`__ docs describe adding
   ``"awsAuthRefresh": "aws sso login --profile myprofile"`` to your config,
   this is only for when you're running Claude Code *without* a container. The
   :ref:`refresh` script will take care of this for us.

Step 3. Claude Code locally (Podman container)
----------------------------------------------

Since we're using AWS SSO to authenticate, **we do not need to install Claude
Code locally**. This is in contrast to Codex, which we had to install locally in
order to be able to use `codex login`.

1. On a local Mac, ensure you have Podman Desktop installed and running and
   that you are in a directory you are comfortable giving Claude access to.

2. Run :cmd:`launch.py claude`. This will prompt you to set up the color scheme
   and allow permissions in the directory.

3. Submit a prompt like "testing" to confirm that the model responds.


.. details:: What did this do?

   - :cmd:`launch.py` detected that you're running on a Mac and that Podman is the
     right container runtime
   - If you didn't have any previous Claude Code config, it created
     a :file:`~/.claude.json` file with an empty JSON array (``{}``) and/or an
     empty :file:`~/.claude` directory.
   - The default podman image was downloaded if needed, a container was created
   - The :file:`~/.claude.json` file and any existing :file:`~/.claude` directory was mounted into the container
   - Host variables starting with ``CLAUDE_CODE`` were passed through to the container
   - Because ``CLAUDE_CODE_USE_BEDROCK=1`` was set, host ``AWS_*`` variables and the :file:`~/.aws` directory were also passed through so Claude could use AWS credentials

Step 4. Claude Code remote (Singularity)
----------------------------------------

1. Run the following locally (this example uses the :nih:`NIH-specific` host, biowulf.nih.gov):

   .. code-block:: bash

      refresh.py --remote biowulf.nih.gov

2. Log in to the remote system. If Using NIH's Biowulf, get an interactive node and load the Singularity module:

   .. code-block:: bash

      ssh biowulf.nih.gov      # log in
      sinteractive             # allocate interactive node
      module load singularity  # make Singularity available

3. If you don't already have it available, download the :ref:`launch` script from the repo to the remote.

4. Run the following:

   .. code-block:: bash

      launch.py claude


.. details:: What did this do?

   - :file:`refresh.py` ran :cmd:`aws sso login` if needed, and then pushed the
     appropriate credentials files (:file:`~/.aws`) to the remote.
   - :file:`launch.py` detected that you're running on Linux so Singularity is the appropriate container runtime
   - The default Singularity image was downloaded
   - Similar to running locally in a Podman container, the appropriate configs
     were mounted into the running Singularity container. With
     ``CLAUDE_CODE_USE_BEDROCK=1``, that includes host ``AWS_*`` variables and
     :file:`~/.aws`.

Step 5. Configure Claude Code
-----------------------------

See :ref:`config-claude` for details.


Step 6. Routine usage
---------------------

Your AWS credentials will eventually time out, and when this happens Claude Code
will have connection issues. See :ref:`ts-credentials-expired` for how to
diagnose this. If this happens mid-session, you can run :cmd:`refresh.py` on
your local machine, with the ``--remote`` argument if your session is on
a remote system.

This will update the credentials files in place, and since they are mounted
"live" into the container, the running Claude Code session will see the update,
and will be able to connect on the next prompt submission.

Each time you start the container, you will use the latest built image from
this repo, ``ghcr.io/nichd-bspc/llm:latest`` for podman or
``oras://ghcr.io/nichd-bspc/llm-sif:latest`` for Singularity.


.. seealso::

   - `How Claude Code works <https://code.claude.com/docs/en/how-claude-code-works>`__
   - `Understanding the context window <https://code.claude.com/docs/en/context-window>`__
   - `Common workflows <https://code.claude.com/docs/en/common-workflows>`__
   - `Explore the .claude directory <https://code.claude.com/docs/en/claude-directory>`__
