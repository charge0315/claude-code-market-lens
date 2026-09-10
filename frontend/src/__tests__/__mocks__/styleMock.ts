// CSS import を無害化するモック（jest は CSS を解釈しない）。
const styleMock: Record<string, never> = {};
export default styleMock;
