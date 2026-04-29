from datetime import datetime

project = "LLM Tools"
author = "NIH"
copyright = f"{datetime.now().year}, NIH"
import sys
sys.path.insert(0, ".")
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.githubpages",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "details_ext",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "MIGRATION.md"]

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_title = "LLM containers"

html_theme_options = {
    "light_css_variables": {
        "color-brand-primary": "#005ea2",
        "color-brand-content": "#005ea2",
    },
    "dark_css_variables": {
        "color-brand-primary": "#7cc4fa",
        "color-brand-content": "#7cc4fa",
    },
}

rst_prolog = """
.. role:: nih
   :class: nih-badge

.. role:: cmd(code)
   :class: cmd-role
"""

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "boto3": ("https://boto3.amazonaws.com/v1/documentation/api/latest", None),
}

pygments_style = "default"
