# https://www.sphinx-doc.org/en/master/usage/configuration.html
import sys
from pathlib import Path

sys.path.append(Path(__file__).parent.parent / 'src')

project = 'aiven-monitor'
copyright = '2021, kevin michel'
author = 'kevin michel'
extensions = ['sphinx.ext.autodoc', 'sphinx_rtd_theme']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
html_theme = 'sphinx_rtd_theme'
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
}
