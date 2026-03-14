# Contributing to SICRY™

Thanks for your interest. SICRY™ is a single-file tool — keep that constraint in mind.

## Ground rules

- All changes must keep `sicry.py` as a single self-contained file
- No new required dependencies beyond `requests[socks] beautifulsoup4 python-dotenv stem`
- Public API (`search`, `fetch`, `check_tor`, `renew_identity`, `ask`, `dispatch`) must not break
- Python 3.9+ compatibility required

## How to contribute

1. Fork the repo
2. Create a branch: `git checkout -b fix/your-fix` or `feat/your-feature`
3. Make changes, run `python3 -m py_compile sicry.py` to verify syntax
4. Test locally: `python3 sicry.py tools` (no Tor needed) and `python3 sicry.py check` (Tor needed)
5. Open a PR against `main` with a clear description of what and why

## Adding/fixing search engines

Edit the `ENGINES` list in `sicry.py`. Each engine needs: `name`, `url` (with `{query}` placeholder), `type` (`onion` or `clearnet`), and optional `result_selector`.

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).

## License

By contributing you agree your contributions are licensed under MIT.
