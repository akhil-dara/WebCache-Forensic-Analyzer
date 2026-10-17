// LAST in ASSET_ORDER. A frozen, read-only API (for a reviewer at the
// console, and for the tests), then start.
window.WC = Object.freeze(Object.assign({}, API));
start();
