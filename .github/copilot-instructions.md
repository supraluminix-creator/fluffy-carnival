# Copilot Coding Agent Instructions

## Repository Purpose

This is a Scrypto repository for developing smart contracts and decentralized applications on the Radix DLT platform. Scrypto is a Rust-based language specifically designed for building secure and efficient decentralized applications with asset-oriented programming.

## Suitable Tasks for Copilot

The following types of tasks are well-suited for the Copilot coding agent:

- **Documentation improvements**: Update README files, add code comments, improve inline documentation
- **Test coverage**: Write unit tests and integration tests for non-critical components
- **Code formatting and linting**: Apply consistent formatting and fix linting issues
- **Refactoring small functions**: Improve code structure in isolated utility functions
- **Adding error handling**: Improve error messages and error handling patterns
- **Creating examples**: Add example usage code and sample implementations
- **Configuration updates**: Update build configurations, CI/CD workflows
- **Dependency updates**: Update dependencies with proper testing

## Tasks Not Suitable for Copilot

These tasks require human expertise and should not be handled by the coding agent:

- **Security-critical code**: Smart contract logic involving asset transfers, authentication, or access control
- **Core business logic**: Blueprint implementations and critical state management
- **Major architectural changes**: Restructuring component designs or changing fundamental patterns
- **Production deployments**: Any changes to deployment scripts or production configurations
- **Cryptographic implementations**: Custom cryptographic functions or security-sensitive code
- **Complex economic logic**: Token economics, fee structures, or incentive mechanisms

## Project Structure Overview

```
/
├── .github/           # GitHub configuration and workflows
├── src/               # Source code for Scrypto blueprints (when added)
├── tests/             # Unit and integration tests (when added)
├── examples/          # Example implementations (when added)
├── LICENSE            # MIT License
└── README.md          # Project documentation
```

## Build & Test Instructions

When source code is added to this repository, the typical Scrypto workflow will be:

### Prerequisites
- Install Scrypto: Follow the [Radix Scrypto installation guide](https://docs.radixdlt.com/docs/getting-rust-scrypto)
- Ensure Rust toolchain is properly configured

### Building
```bash
scrypto build
```

### Testing
```bash
scrypto test
```

### Formatting
```bash
cargo fmt
```

### Linting
```bash
cargo clippy -- -D warnings
```

## Development Guidelines

### Code Style
- Follow Rust standard formatting with `cargo fmt`
- Use `cargo clippy` to catch common issues
- Ensure all public functions and modules have documentation comments
- Use meaningful variable and function names that clearly express intent

### Testing Standards
- Write unit tests for all public functions
- Include integration tests for blueprint interactions
- Test both success and failure cases
- Aim for meaningful test coverage (focus on critical paths rather than arbitrary percentages)

### Documentation
- Add doc comments (`///`) for all public APIs
- Include examples in doc comments where helpful
- Keep README.md up to date with project changes
- Document any non-obvious design decisions

### Error Handling
- Use appropriate error types (panics for invariants, Results for recoverable errors)
- Provide clear, actionable error messages
- Document error conditions in function documentation

## Contribution Guidelines

### Code Reviews
- Keep pull requests focused and reasonably sized
- Write clear PR descriptions explaining the "what" and "why"
- Respond to review feedback promptly
- Ensure all tests pass before requesting review

### Commit Messages
- Use clear, descriptive commit messages
- Start with a verb in imperative mood (e.g., "Add", "Fix", "Update")
- Reference issue numbers when applicable

### Pull Request Etiquette
- Link to related issues in PR description
- Add appropriate labels to PRs
- Ensure CI/CD checks pass before requesting review
- Keep the PR branch up to date with the main branch
- Respond to feedback by pushing new commits (avoid force-pushing during review)

## Security Considerations

Since this is a Scrypto project dealing with blockchain and potentially valuable assets:

- **Never** commit private keys, mnemonics, or sensitive credentials
- **Always** validate inputs in blueprint methods
- **Review** all asset-handling code carefully
- **Test** edge cases and potential attack vectors
- **Follow** Scrypto best practices for access control and asset management

## Additional Resources

- [Scrypto Documentation](https://docs.radixdlt.com/docs)
- [Radix GitHub Examples](https://github.com/radixdlt/official-examples)
- [Rust Programming Language Book](https://doc.rust-lang.org/book/)
