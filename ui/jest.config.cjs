/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: { jsx: "react-jsx", esModuleInterop: true } }],
  },
  moduleNameMapper: {
    "\\.(css|less|scss)$": "identity-obj-proxy",
    "\\.(svg|png|jpg)$": "<rootDir>/src/__mocks__/fileMock.cjs",
  },
  setupFilesAfterEnv: ["@testing-library/jest-dom"],
  testMatch: ["<rootDir>/src/**/*.test.{ts,tsx}"],
};
