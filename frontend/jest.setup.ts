import '@testing-library/jest-dom';
import { toHaveNoViolations } from 'jest-axe';

// jest-axe v11 の toHaveNoViolations は既に matcher 関数の形で export されている。
expect.extend(toHaveNoViolations);
