function f(n) {
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
