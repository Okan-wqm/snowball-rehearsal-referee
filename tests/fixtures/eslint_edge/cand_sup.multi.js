function f(n) {
  // eslint-disable-next-line prefer-template
  const r = "a" +
    n +
    "b";
  return r;
}
function g() {
  f(1);
  return;
}
module.exports = g;
