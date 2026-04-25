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
