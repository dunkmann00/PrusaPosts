## GapCloser

GapCloser attempts to close small gaps/holes that may be present at the start of
extrusions after travel moves with deretractions. It will move the starting
point of the extrusion back by `--back-up-distance`, which by default is 1.0mm.
This can be configured as necessary.

This can be run by either directly invoking it with Python, or as a PrusaSlicer
post-processing script.

The g-code this produces is quite stable. I found the resulting print to
successfully close minor holes I was seeing in a PETG print I was trying to make
sure was watertight. If your print has big gaps/holes I cannot say whether this
would help since I haven't been able to test that. But if you have tried a bunch
of other things to fix your print and nothing is working, I would definitely
recommend giving this a shot! As always with post processing scripts, I
recommend that you always check the g-code preview before sending it to the
printer!
