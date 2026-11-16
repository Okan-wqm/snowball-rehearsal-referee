module.exports = [{
  files: ["**/*.js"],
  languageOptions: { sourceType: "commonjs", globals: { module: "writable", require: "readonly" } },
  linterOptions: { reportUnusedDisableDirectives: "warn" },
  rules: { "prefer-const": "error", "no-var": "warn", "dot-notation": "error", "no-unused-vars": "error", "prefer-template": "error", "no-useless-return": "error" },
}];
