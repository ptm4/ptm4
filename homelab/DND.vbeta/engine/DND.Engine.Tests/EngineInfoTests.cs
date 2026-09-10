using System.Linq;
using DND.Engine;
using Xunit;

namespace DND.Engine.Tests
{
    public class EngineInfoTests
    {
        [Fact]
        public void Version_IsSet()
        {
            Assert.Equal("0.1.0", EngineInfo.Version);
        }

        [Fact]
        public void EngineAssembly_HasNoUnityReference()
        {
            var refs = typeof(EngineInfo).Assembly.GetReferencedAssemblies().Select(a => a.Name);
            Assert.DoesNotContain(refs, n => n != null && n.StartsWith("UnityEngine"));
        }
    }
}
