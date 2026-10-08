# Synthetic extraction fixtures

All PDF fixtures contain synthetic test content, not enterprise/private documents.
DP-12 reuses `mixed.pdf` for native pages 1/4, OCR page 2, and blank page 3;
existing unit tests retain empty/encrypted/image-only/Unicode/resource fixtures.

`quality.pdf` is a deterministic, checked-in, uncompressed PDF 1.4 with Helvetica
text boxes on pages 1 and 3 and a blank page 2. Both content pages have a repeated
report label/footer, an ordinary paragraph, list-like lines, and table-like text.
There are no inferred headings, logical tables, or semantic list claims: native
PDF extraction emits paragraphs and preserves original page membership.
It contains only catalog/pages/font objects and explicit text drawing commands,
with fixed object ordering/xref offsets and no timestamps or random identifiers.

DP-12 TXT/Markdown sources are readable constants in the cross-component
`conftest.py`, including multibyte oversized units. No fixture generation occurs
at test runtime; constructor limits are reduced for resource-bound tests.
