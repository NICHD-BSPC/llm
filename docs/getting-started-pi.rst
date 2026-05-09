Getting started: Pi
===================

`Pi <https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent>`__ is
a minimal coding harness. Unlike Codex and Claude Code, which are closely tied
to OpenAI and Anthropic respectively, Pi is agnostic to model.

Like Claude Code, Pi can use Amazon Bedrock. So if you have already completed
:doc:`getting-started-claude`, then you're most of the way set up to use Pi.

The one thing you should add, for using Bedrock, is to export the
``PI_USE_BEDROCK`` environment variable:

.. code-block:: bash

   export PI_USE_BEDROCK=1

Then run like this:

.. code-block:: bash

   launch.py pi

On remote systems where Pi has trouble with proxy-driven AWS auth, use exported
session credentials:

.. code-block:: bash

   # local machine
   refresh.py --remote your.remote.host

   # remote shell
   launch.py pi

See :doc:`tools` for additional :ref:`launch` options (extra mounts,
certificates, dry-run, etc.) and :doc:`aws-sso` for the full SSO setup if
you have not already completed it as part of :doc:`getting-started-claude`.
