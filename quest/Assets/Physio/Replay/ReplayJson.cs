#nullable enable
using System;
using System.Globalization;
using System.IO;
using System.Numerics;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Physio.Replay
{
    internal static class ReplayJson
    {
        internal static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidDataException(message);
        }

        internal static JObject Read(byte[] bytes)
        {
            var text = new UTF8Encoding(false, true).GetString(bytes);
            // Newtonsoft also accepts JavaScript syntax; require JSON grammar before creating tokens.
            new Syntax(text).Validate();
            using var input = new StringReader(text);
            using var reader = new JsonTextReader(input) { DateParseHandling = DateParseHandling.None, MaxDepth = 8 };
            return JObject.Load(reader, new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error });
        }

        internal static JObject Object(JToken? token, params string[] fields)
        {
            Require(token is JObject, "Expected a metadata object.");
            var value = (JObject)token!;
            Require(value.Count == fields.Length, "Missing or unknown metadata field.");
            foreach (var field in fields) Require(value.Property(field, StringComparison.Ordinal) != null, "Missing metadata field.");
            return value;
        }

        internal static JArray Array(JToken? token, int? count = null)
        {
            Require(token is JArray, "Expected a metadata array.");
            var value = (JArray)token!;
            Require(!count.HasValue || value.Count == count.Value, "Metadata array count mismatch.");
            return value;
        }

        internal static string String(JToken? token, int maxLength = 200)
        {
            Require(token?.Type == JTokenType.String, "Expected a metadata string.");
            var value = (string)token!;
            StringLength(value, maxLength);
            return value;
        }

        internal static void StringLength(string value, int maxLength)
        {
            var length = 0;
            for (var i = 0; i < value.Length; i++, length++)
                if (char.IsHighSurrogate(value[i]) && i + 1 < value.Length && char.IsLowSurrogate(value[i + 1])) i++;
            Require(length > 0 && length <= maxLength, "Metadata string length is outside its bound.");
        }

        internal static bool Boolean(JToken? token)
        {
            Require(token?.Type == JTokenType.Boolean, "Expected a boolean mask.");
            return (bool)token!;
        }

        internal static BigInteger Integer(JToken? token, int minimum = 0)
        {
            Require(token?.Type == JTokenType.Integer, "Expected an integer, without a fractional/exponent representation.");
            var raw = ((JValue)token!).Value;
            var value = raw is BigInteger big ? big : new BigInteger((long)raw!);
            Require(value >= minimum && !double.IsInfinity((double)value), "Integer is outside its finite range.");
            return value;
        }

        internal static int Count(JToken? token)
        {
            var value = Integer(token, 1);
            Require(value <= int.MaxValue, "Count exceeds the supported allocation range.");
            return (int)value;
        }

        internal static double Number(JToken? token)
        {
            Require(token?.Type == JTokenType.Float || token?.Type == JTokenType.Integer, "Expected a numeric value.");
            var value = (double)token!;
            Require(!double.IsNaN(value) && !double.IsInfinity(value), "Number must be finite.");
            return value;
        }

        internal static Guid Uuid(JToken? token)
        {
            Require(Guid.TryParseExact(String(token), "D", out var value), "Expected a UUID.");
            return value;
        }

        internal static BigInteger Timestamp(JToken? token)
        {
            var value = String(token, 30);
            Require(value.Length == 1 || value[0] != '0', "Timestamp must be a canonical decimal string.");
            foreach (var c in value) Require(c >= '0' && c <= '9', "Timestamp must contain decimal digits only.");
            return BigInteger.Parse(value, CultureInfo.InvariantCulture);
        }

        private sealed class Syntax
        {
            private readonly string text;
            private int offset;
            internal Syntax(string text) { this.text = text; }
            private char Current => offset < text.Length ? text[offset] : '\0';
            private static bool Digit(char c) => c >= '0' && c <= '9';

            internal void Validate()
            {
                Value(0);
                Space();
                Require(offset == text.Length, "Trailing JSON content.");
            }

            private void Space()
            {
                while (Current == ' ' || Current == '\t' || Current == '\n' || Current == '\r') offset++;
            }

            private void Expect(char c)
            {
                Space();
                Require(Current == c, "Malformed JSON syntax.");
                offset++;
            }

            private void Value(int depth)
            {
                Require(depth <= 8, "JSON nesting exceeds the replay schema.");
                Space();
                if (Current == '{') Container(depth, true);
                else if (Current == '[') Container(depth, false);
                else if (Current == '"') Quoted();
                else if (Current == 't') Literal("true");
                else if (Current == 'f') Literal("false");
                else if (Current == 'n') Literal("null");
                else NumberToken();
            }

            private void Container(int depth, bool isObject)
            {
                offset++;
                Space();
                var close = isObject ? '}' : ']';
                if (Current == close) { offset++; return; }
                while (true)
                {
                    if (isObject) { Quoted(); Expect(':'); }
                    Value(depth + 1);
                    Space();
                    if (Current == close) { offset++; return; }
                    Expect(',');
                    Space();
                }
            }

            private void Literal(string value)
            {
                Require(offset + value.Length <= text.Length &&
                    string.CompareOrdinal(text, offset, value, 0, value.Length) == 0, "Invalid JSON literal.");
                offset += value.Length;
            }

            private void NumberToken()
            {
                if (Current == '-') offset++;
                var integerStart = offset;
                if (Current == '0') offset++;
                else
                {
                    Require(Current >= '1' && Current <= '9', "Malformed JSON number.");
                    while (Digit(Current)) offset++;
                }
                if (Current != '.' && Current != 'e' && Current != 'E')
                    Require(offset - integerStart <= 309, "JSON integer exceeds the finite numeric range.");
                if (Current == '.') { offset++; Digits(); }
                if (Current == 'e' || Current == 'E')
                {
                    offset++;
                    if (Current == '+' || Current == '-') offset++;
                    Digits();
                }
            }

            private void Digits()
            {
                Require(Digit(Current), "Missing JSON number digits.");
                while (Digit(Current)) offset++;
            }

            private void Quoted()
            {
                Expect('"');
                while (offset < text.Length)
                {
                    var c = text[offset++];
                    if (c == '"') return;
                    Require(c >= 0x20, "Unescaped control character in JSON string.");
                    if (c != '\\') continue;
                    Require(offset < text.Length, "Truncated JSON escape.");
                    var escape = text[offset++];
                    if (escape == 'u')
                    {
                        var code = Hex();
                        if (code >= 0xd800 && code <= 0xdbff)
                        {
                            Require(offset + 2 <= text.Length && text[offset] == '\\' && text[offset + 1] == 'u', "Unpaired Unicode surrogate.");
                            offset += 2;
                            var low = Hex();
                            Require(low >= 0xdc00 && low <= 0xdfff, "Unpaired Unicode surrogate.");
                        }
                        else Require(code < 0xdc00 || code > 0xdfff, "Unpaired Unicode surrogate.");
                    }
                    else Require("\"\\/bfnrt".IndexOf(escape) >= 0, "Invalid JSON escape.");
                }
                throw new InvalidDataException("Unterminated JSON string.");
            }

            private int Hex()
            {
                Require(offset + 4 <= text.Length, "Truncated Unicode escape.");
                var code = 0;
                for (var i = 0; i < 4; i++)
                {
                    var c = text[offset++];
                    var digit = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
                    Require(digit >= 0, "Invalid Unicode escape.");
                    code = code * 16 + digit;
                }
                return code;
            }
        }
    }
}
