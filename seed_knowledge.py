import os
import logging
from dotenv import load_dotenv
from database import DatabaseManager
from heroku_inference import InferenceClient
import psycopg2
from psycopg2.extras import execute_values

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Security knowledge entries - expanded to 25 detailed articles with mock URLs
SECURITY_KNOWLEDGE = [
    {
        "title": "Data Exfiltration Prevention",
        "content": "Implement network segmentation, monitor data transfers, and use DLP tools to prevent unauthorized data exfiltration. Configure data loss prevention tools to monitor sensitive data movements across networks. Establish data classification processes to identify high-value assets. Set up egress filtering at network boundaries. Review cloud storage permissions to prevent accidental public exposure. For more details, see https://security-kb.example.com/data-exfiltration-prevention-101",
        "category": "Network Security"
    },
    {
        "title": "Access Control Best Practices",
        "content": "Enforce strong password policies, implement MFA, and regularly audit access permissions to maintain security. Implement zero trust architecture for sensitive systems. Use just-in-time access for privileged accounts. Conduct quarterly privilege reviews to identify over-permissioned accounts. Implement password rotation for service accounts. For detailed implementation guidelines, refer to https://security-kb.example.com/access-control-framework",
        "category": "Access Control"
    },
    {
        "title": "Incident Response Plan",
        "content": "Develop and maintain an incident response plan that includes clear roles, communication protocols, and recovery procedures. Define escalation thresholds for different types of security incidents. Create scenario-based playbooks for common attack vectors. Establish secure communication channels for incident responders. Schedule regular tabletop exercises to test IR capabilities. Additional resources available at https://security-kb.example.com/incident-response-playbook",
        "category": "Incident Response"
    },
    {
        "title": "Secure Configuration Management",
        "content": "Follow security hardening guidelines, disable unnecessary services, and regularly update system configurations. Implement configuration management tools to track and enforce secure baselines. Use CIS benchmarks as reference standards. Automate compliance checking with security scanning tools. Document exceptions with business justifications and review periodically. See comprehensive checklist at https://security-kb.example.com/secure-configuration-standards",
        "category": "System Security"
    },
    {
        "title": "Enterprise Security Monitoring",
        "content": "Implement comprehensive logging, use SIEM solutions, and conduct regular security assessments. Configure centralized log collection with retention policies aligned to compliance requirements. Develop custom detection rules for your environment's unique threats. Set up automated alerting for critical security events. Establish 24/7 monitoring procedures for SOC operations. View monitoring architecture diagram at https://security-kb.example.com/security-monitoring-framework",
        "category": "Security Operations"
    },
    {
        "title": "Vulnerability Management Lifecycle",
        "content": "Regularly scan for vulnerabilities, prioritize patches based on risk scoring, and maintain an up-to-date inventory of assets. Implement automated vulnerability scanning for all network segments. Define SLAs for remediation based on CVSS scores and business impact. Establish patch testing procedures before production deployment. Track vulnerability metrics to measure program effectiveness. Complete program documentation available at https://security-kb.example.com/vulnerability-management-program",
        "category": "Vulnerability Management"
    },
    {
        "title": "Security Awareness Program",
        "content": "Conduct regular security training, simulate phishing attacks, and promote security-conscious behavior. Develop role-based security training modules targeting specific job functions. Measure effectiveness with pre/post assessments. Create a security champions network across departments. Implement a security incident reporting portal with recognition for good catches. Training materials available at https://security-kb.example.com/security-awareness-hub",
        "category": "Security Training"
    },
    {
        "title": "Regulatory Compliance Framework",
        "content": "Stay updated with regulatory requirements, perform regular audits, and maintain documentation of security controls. Map security controls to multiple compliance frameworks (GDPR, HIPAA, PCI-DSS, etc.). Implement continuous compliance monitoring. Prepare audit-ready documentation including evidence collection procedures. Schedule mock audits before official assessments. Compliance mapping tool available at https://security-kb.example.com/compliance-mapping",
        "category": "Compliance"
    },
    {
        "title": "Cloud Security Architecture",
        "content": "Design secure cloud environments with proper IAM configurations, network controls, and encryption. Implement cloud security posture management tools to detect misconfigurations. Use infrastructure as code with security scanning in CI/CD pipelines. Configure cloud-native security services for each provider. Implement least privilege principles for cloud resources. Cloud security reference architecture at https://security-kb.example.com/cloud-security-blueprint",
        "category": "Cloud Security"
    },
    {
        "title": "Mobile Device Security",
        "content": "Secure corporate and BYOD mobile devices with MDM solutions, application controls, and data protection. Deploy mobile device management with conditional access policies. Implement app whitelisting for corporate devices. Configure remote wipe capabilities for lost devices. Enforce encryption for data at rest on mobile devices. Mobile security policy template at https://security-kb.example.com/mobile-security-standards",
        "category": "Endpoint Security"
    },
    {
        "title": "Third-party Risk Management",
        "content": "Assess and monitor vendor security practices through questionnaires, audits, and continuous monitoring. Categorize vendors based on data access and business impact. Implement standard security requirements in all vendor contracts. Perform annual reassessments of critical vendors. Monitor for vendor data breaches through threat intelligence feeds. Vendor assessment framework at https://security-kb.example.com/vendor-risk-framework",
        "category": "Risk Management"
    },
    {
        "title": "Email Security Controls",
        "content": "Implement SPF, DKIM, and DMARC to prevent email spoofing and phishing attacks. Configure anti-spam and anti-malware filtering for inbound and outbound email. Deploy attachment sandboxing for suspicious files. Implement URL rewriting and scanning for embedded links. Set up impersonation protection for executives. Email security architecture diagram at https://security-kb.example.com/email-security-defense",
        "category": "Email Security"
    },
    {
        "title": "Secure Software Development",
        "content": "Integrate security into the SDLC with threat modeling, code reviews, and automated security testing. Implement security requirements at project inception. Train developers on secure coding practices. Configure pre-commit hooks for security checks. Perform penetration testing before production deployment. DevSecOps implementation guide at https://security-kb.example.com/secure-sdlc-guide",
        "category": "Application Security"
    },
    {
        "title": "Privileged Access Management",
        "content": "Secure privileged accounts with vaulting, session monitoring, and just-in-time access. Implement password rotation for admin accounts. Record and audit privileged sessions. Require approval workflows for sensitive system access. Eliminate hard-coded credentials in scripts and applications. PAM implementation roadmap at https://security-kb.example.com/pam-strategy",
        "category": "Identity Management"
    },
    {
        "title": "Network Segmentation Strategy",
        "content": "Divide networks into security zones to limit the blast radius of breaches and improve access control. Implement micro-segmentation for critical assets. Configure east-west traffic filtering between segments. Use software-defined networking for dynamic segmentation. Monitor cross-segment traffic for anomalies. Network segmentation architecture at https://security-kb.example.com/network-segmentation-design",
        "category": "Network Security"
    },
    {
        "title": "Endpoint Detection and Response",
        "content": "Deploy EDR solutions to detect, investigate, and remediate advanced threats on endpoints. Configure behavioral analytics for anomaly detection. Implement automated response playbooks for common threats. Maintain forensic data collection capabilities. Integrate with SIEM for correlation and investigation. EDR evaluation criteria at https://security-kb.example.com/edr-selection-guide",
        "category": "Endpoint Security"
    },
    {
        "title": "Data Classification Framework",
        "content": "Classify data based on sensitivity and implement appropriate controls for each level. Define standardized classification levels across the organization. Implement visual markings for documents and emails. Configure DLP rules based on classification tags. Provide user training on handling different data types. Data classification policy at https://security-kb.example.com/data-classification-guide",
        "category": "Data Security"
    },
    {
        "title": "Security Metrics and KPIs",
        "content": "Establish meaningful security metrics to measure program effectiveness and drive improvements. Track mean time to detect and respond to incidents. Monitor vulnerability remediation performance. Measure security awareness program effectiveness. Create executive dashboards for security posture visibility. Security metrics framework at https://security-kb.example.com/security-metrics-dashboard",
        "category": "Security Operations"
    },
    {
        "title": "Security Architecture Review Process",
        "content": "Implement a formal review process for new technologies and architectural changes. Develop security architecture principles and requirements. Create security design patterns for common use cases. Establish architecture review boards with clear approval criteria. Document and track architectural decisions. Architecture review templates at https://security-kb.example.com/architecture-review-toolkit",
        "category": "Security Architecture"
    },
    {
        "title": "Threat Intelligence Program",
        "content": "Establish a threat intelligence program to proactively identify and respond to emerging threats. Subscribe to industry-specific threat feeds. Develop an internal intelligence collection capability. Create a threat intelligence sharing process across teams. Integrate intelligence with detection and response. Threat intelligence framework at https://security-kb.example.com/threat-intel-program",
        "category": "Threat Management"
    },
    {
        "title": "Disaster Recovery Planning",
        "content": "Develop comprehensive DR plans to ensure business continuity during security incidents. Define recovery time objectives for critical systems. Implement backup strategies with immutable storage. Conduct regular DR tests with realistic scenarios. Document recovery procedures for different types of incidents. DR planning template at https://security-kb.example.com/dr-planning-guide",
        "category": "Business Continuity"
    },
    {
        "title": "Cryptography Standards",
        "content": "Implement strong cryptography for data protection with proper key management. Define approved algorithms and key lengths for different use cases. Establish crypto-agility to handle algorithm deprecation. Implement secure key generation and storage practices. Conduct regular cryptographic inventory assessments. Cryptography policy at https://security-kb.example.com/crypto-standards",
        "category": "Data Security"
    },
    {
        "title": "IoT Security Guidelines",
        "content": "Secure Internet of Things devices with network isolation, regular updates, and strong authentication. Implement dedicated networks for IoT devices. Disable unnecessary services and ports. Create device inventory and vulnerability management processes. Monitor for abnormal device behavior. IoT security checklist at https://security-kb.example.com/iot-security-framework",
        "category": "IoT Security"
    },
    {
        "title": "Zero Trust Implementation",
        "content": "Adopt zero trust principles with never trust, always verify approach to security architecture. Implement identity-based access controls for all resources. Deploy continuous verification of user and device trust. Minimize accessible service attack surface. Enforce least privilege access to all resources. Zero trust roadmap at https://security-kb.example.com/zero-trust-model",
        "category": "Security Architecture"
    },
    {
        "title": "Security Automation Strategies",
        "content": "Implement security automation to increase efficiency and response speed for common security tasks. Automate vulnerability scanning and remediation workflows. Create playbooks for incident response actions. Implement auto-remediation for known good fixes. Use orchestration platforms to connect security tools. Automation use cases at https://security-kb.example.com/security-automation-handbook",
        "category": "Security Operations"
    }
]

def seed_database():
    """Seed the database with security knowledge."""
    conn = None
    cur = None
    try:
        # Initialize the OpenAI client
        client = InferenceClient()
        
        # Connect to the database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        conn.autocommit = False  # Start with autocommit off for transaction control
        cur = conn.cursor()

        # Enable the vector extension if possible
        vector_enabled = False
        try:
            # Use a separate transaction for extension creation
            conn.autocommit = True  # Extensions require autocommit mode
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            vector_enabled = True
            logger.info("Successfully enabled vector extension")
        except Exception as e:
            logger.warning(f"Could not enable vector extension: {e}")
            logger.warning("Continuing without vector embeddings")
        finally:
            conn.autocommit = False  # Return to transaction mode
            
        # Drop existing tables - each in its own transaction
        try:
            conn.autocommit = True
            cur.execute("DROP TABLE IF EXISTS incident_knowledge_references CASCADE")
            logger.info("Dropped incident_knowledge_references table")
        except Exception as e:
            logger.warning(f"Could not drop incident_knowledge_references table: {e}")
        finally:
            conn.autocommit = False
            
        try:
            conn.autocommit = True
            cur.execute("DROP TABLE IF EXISTS security_knowledge CASCADE")
            logger.info("Dropped security_knowledge table")
        except Exception as e:
            logger.warning(f"Could not drop security_knowledge table: {e}")
        finally:
            conn.autocommit = False

        # Start a fresh transaction
        conn.autocommit = False
        
        # Create the security_knowledge table
        if vector_enabled:
            try:
                # Try to create with vector support
                cur.execute("""
                    CREATE TABLE security_knowledge (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT NOT NULL,
                        embedding vector(1024),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logger.info("Created security_knowledge table with vector support")
            except Exception as e:
                logger.warning(f"Could not create table with vector support: {e}")
                conn.rollback()  # Rollback the failed transaction
                vector_enabled = False
                
                # Fallback to no vector
                cur.execute("""
                    CREATE TABLE security_knowledge (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        category TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logger.info("Created security_knowledge table without vector support")
        else:
            # Create without vector support
            cur.execute("""
                CREATE TABLE security_knowledge (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Created security_knowledge table without vector support")

        # Try to create incident_knowledge_references table
        try:
            cur.execute("""
                CREATE TABLE incident_knowledge_references (
                    id SERIAL PRIMARY KEY,
                    incident_id INTEGER,
                    knowledge_id INTEGER REFERENCES security_knowledge(id),
                    relevance_score FLOAT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("Created incident_knowledge_references table")
        except Exception as e:
            conn.rollback()
            logger.warning(f"Could not create incident_knowledge_references table: {e}")

        # Insert knowledge entries - commit after each one to avoid transaction issues
        inserted_count = 0
        for knowledge in SECURITY_KNOWLEDGE:
            try:
                if vector_enabled:
                    # Try to generate embedding for the content
                    try:
                        embeddings = client.embeddings_create(
                            model="cohere-embed-multilingual",
                            texts=[knowledge["content"]]
                        )
                        embedding = embeddings[0]

                        # Insert with embedding
                        cur.execute("""
                            INSERT INTO security_knowledge (title, content, category, embedding)
                            VALUES (%s, %s, %s, %s::vector)
                        """, (knowledge["title"], knowledge["content"], knowledge["category"], embedding))
                    except Exception as e:
                        logger.warning(f"Could not generate embedding, inserting without it: {e}")
                        conn.rollback()
                        cur.execute("""
                            INSERT INTO security_knowledge (title, content, category)
                            VALUES (%s, %s, %s)
                        """, (knowledge["title"], knowledge["content"], knowledge["category"]))
                else:
                    # Insert without embedding
                    cur.execute("""
                        INSERT INTO security_knowledge (title, content, category)
                        VALUES (%s, %s, %s)
                    """, (knowledge["title"], knowledge["content"], knowledge["category"]))
                
                conn.commit()  # Commit each insert individually
                inserted_count += 1
                logger.debug(f"Inserted knowledge article: {knowledge['title']}")
            except Exception as e:
                conn.rollback()  # Rollback on error
                logger.error(f"Error inserting knowledge '{knowledge['title']}': {e}")

        logger.info(f"Successfully seeded the database with {inserted_count} security knowledge articles")

    except Exception as e:
        if conn and not conn.closed:
            conn.rollback()
        logger.error(f"Error seeding database: {str(e)}")
        raise
    finally:
        if cur and not cur.closed:
            cur.close()
        if conn and not conn.closed:
            conn.close()

if __name__ == "__main__":
    load_dotenv()
    seed_database() 