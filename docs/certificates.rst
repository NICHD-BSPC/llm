Enterprise TLS certificates
===========================

Some networks (including NIH) intercept SSL/TLS traffic for security
monitoring. This requires trusting additional certificate authorities.

Problem
-------

When running inside a container, the container cannot see certificates
installed on the host machine. This causes SSL/TLS connection failures when
on VPN or certain enterprise networks. Symptoms include ``apt`` output lines
starting with ``Ign:`` during image builds, and connection errors from agent
tools at runtime.

Solution
--------

Download your enterprise certificates and pass them to the container.

:nih:`NIH-specific` Save the NIH DPKI certificate bundle (only reachable on
the NIH network):

.. code-block:: bash

   curl -fSsL -o ~/.certs.pem http://nihdpkicrl.nih.gov/certdata/DPKI-2023-Intermediate-rekey-FullChainBase64.crt

Then either:

1. Set the environment variable in :file:`~/.bashrc`:

   .. code-block:: bash

      export LLM_DEVCONTAINER_CERTS=~/.certs.pem

2. Or pass ``--certs`` to :cmd:`launch.py` for one-off use:

   .. code-block:: bash

      launch.py --certs ~/.certs.pem codex

The same file is also used during image builds; see :doc:`developer`.

If you are still having connection issues after setting up certificates, see
:ref:`ts-ssl-tls` for more troubleshooting steps.

.. seealso::

   See :ref:`launchenv` for the environment variables that are set in the container
   when this mechanism is used.
