import tsParser from '@typescript-eslint/parser';
const nx = (await import('@nx/eslint-plugin')).default;
export default [
  {
    files: ['**/*.ts'],
    languageOptions: { parser: tsParser },
    plugins: { '@nx': nx },
    rules: {
      'no-var': 'error',
      '@nx/enforce-module-boundaries': ['error', { depConstraints: [{ sourceTag: '*', onlyDependOnLibsWithTags: ['*'] }] }],
    },
  },
];
