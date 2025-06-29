# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously and appreciate your help in keeping Bio-MCP secure.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities to:
- **Email**: security@bio-mcp.org (if available)
- **Private GitHub Advisory**: Use GitHub's private vulnerability reporting feature

### What to Include

When reporting a vulnerability, please include:

1. **Description** of the vulnerability
2. **Steps to reproduce** the issue
3. **Potential impact** assessment
4. **Suggested fix** (if you have one)
5. **Your contact information** for follow-up

### Response Timeline

- **Initial Response**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix Timeline**: Depends on severity
  - Critical: 1-7 days
  - High: 7-30 days
  - Medium/Low: Next release cycle

## Security Considerations

### Bioinformatics Data Security

Bio-MCP processes scientific data that may be sensitive. Consider these factors:

#### Local Deployment
- ✅ **Recommended**: Data never leaves your machine
- ✅ **Full Control**: You control all processing
- ✅ **Compliance**: Easier to meet institutional requirements

#### Cloud Deployment
- ⚠️ **Data Transfer**: Consider encryption in transit
- ⚠️ **Storage**: Ensure appropriate cloud security
- ⚠️ **Compliance**: Verify cloud provider meets your requirements

### Input Validation

All MCP servers implement:
- **File size limits** to prevent resource exhaustion
- **Input validation** to prevent injection attacks
- **Sandboxed execution** in containers
- **Temporary file cleanup** to prevent data leakage

### Container Security

Our Docker images:
- Use **official biocontainers** as base images
- Run as **non-root users** when possible
- Include **minimal dependencies** only
- Are **regularly updated** for security patches

### Queue System Security

The job queue system implements:
- **Authentication** for API access
- **Input sanitization** for all job parameters
- **Resource limits** to prevent abuse
- **Secure file storage** with access controls

## Best Practices for Users

### General Security
1. **Keep tools updated** - Use latest versions of MCP servers
2. **Secure your data** - Use appropriate file permissions
3. **Monitor access** - Review MCP server logs regularly
4. **Network security** - Use firewalls and VPNs when appropriate

### Institutional Use
1. **Review compliance** - Ensure Bio-MCP meets your security requirements
2. **Data governance** - Implement appropriate data handling policies
3. **Access control** - Limit who can deploy and configure MCP servers
4. **Audit trails** - Enable logging for compliance purposes

### Development Security
1. **Code review** - All changes require review
2. **Dependency scanning** - Regular security scans of dependencies
3. **Secrets management** - Never commit secrets to repositories
4. **Input validation** - Always validate user inputs

## Vulnerability Disclosure Policy

### Coordinated Disclosure

We follow responsible disclosure practices:

1. **Private reporting** to our team
2. **Assessment and fix** development
3. **Testing** of the fix
4. **Public disclosure** after fix is available
5. **Credit** to the reporter (if desired)

### Public Disclosure Timeline

- **Immediate**: For actively exploited vulnerabilities
- **30 days**: For high-severity issues
- **90 days**: For medium/low severity issues

## Security Contacts

- **Primary**: Open a private GitHub security advisory
- **Secondary**: Create an issue in the appropriate repository with `[SECURITY]` prefix

## Acknowledgments

We thank the following security researchers for their responsible disclosure:

- (None yet - be the first!)

## Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Container Security Best Practices](https://sysdig.com/blog/dockerfile-best-practices/)
- [Python Security Guidelines](https://python-security.readthedocs.io/)
- [GitHub Security Features](https://docs.github.com/en/code-security)