# the document is the workspace

You write prose in this pane, and the pane never competes with you for room.
Every note here is the source of truth: the numbers beside a note are recomputed
from the note on each keystroke, and nothing you did not type is ever inserted
into your prose. The document stays a document. It does not become a transcript.

::: prompt
What is actually lost when a long reply is deleted to fit a context window?
:::
::: reply
Every context window fills up eventually, and the reply that does not fit is dropped, oldest first, because recency is the only thing the window can measure. The words are still on disk. What disappears is the model's ability to see them, so the next answer is quietly built on a shorter conversation that nobody announced. Eviction is blind in a second way as well: it removes whichever message happens to be oldest rather than whichever happens to be irrelevant, so the reply that took the longest to produce is the first one thrown away. Compression is a different rule for the same budget. Instead of keeping what is recent, keep what bears on the question being asked, and let the rest stay retrievable rather than hoping it survived. The difference matters most for the sentence that ties a fact to where it came from, which is exactly the sentence an eviction cannot preserve and a reader cannot reconstruct.
:::

## what a citation is

A citation is not decoration. A citation is a claim that a sentence traces back
to a source, and the quote is the part of that source you are willing to be held
to. Evidence needs both: a claim with a source but no quote cannot be checked,
and a quote with no source is an anecdote. If the source is lost when a context
window evicts a reply, then the evidence in that reply silently degrades into
assertion, and every later claim inherits the damage without anyone noticing.

## where the reading time goes

A reply can be four hundred words and entirely useful, and still be the wrong
thing to put in front of someone who is holding one question. What a reader
needs is the sentence that bears on the question they asked, with the rest one
click away and fully available to whatever process reads the file next. That is
compression as an act of attention rather than an act of storage: the same reply
should read differently depending on which gap is open, and it should say so
plainly when it has nothing to offer that gap at all.

::: code
# the overlay is arithmetic, not inference
assert len(notes) == 3
:::

Two live formulas, typed into the prose: !gap(window, citation) reports the hole
between those clusters, and !hops(claim, window) reports what it would cost to
cross it.

So the argument has three parts that do not yet meet. The pane and the prose
belong to the writer. The context window and the reply belong to the model. The
citation and the evidence belong to whoever has to trust the result. There is no
sentence in this document that connects the middle part to the last one, which is
the whole reason this page is worth keeping rather than shipping.
